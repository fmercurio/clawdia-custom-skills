"""Synthetic authority/provider plus real HTTPS; never access an actual vault."""
import contextlib
import dataclasses
import hashlib
import http.server
import importlib.util
import io
import json
import os
from pathlib import Path
import secrets
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('private_consumer_core', ROOT/'scripts/private_consumer_core.py')
assert SPEC is not None and SPEC.loader is not None
SCRATCH = Path(os.environ.get('VW_TEST_SCRATCH', str(ROOT.parents[2]))).resolve()
ops = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ops
SPEC.loader.exec_module(ops)
ITEM = '00000000-0000-0000-0000-000000000001'
COLLECTION = '00000000-0000-0000-0000-000000000002'
CANARY = 'SYNTHETIC-NOT-A-REAL-CREDENTIAL'
BODY = b'{"synthetic_acceptance":true}'


class SyntheticProvider:
    """Deliberately not a Bitwarden connector. Tests the private interface only."""
    def __init__(self):
        self.locked = True
        self.reads = 0
        self.cleanup_ok = True
        self.cleanup_raises = False
        self.fail = False
        self.visible_items = {ITEM}
        self.visible_collections = {COLLECTION}
        self.permissions = True
        self.during_open = lambda: None

    def parent_locked(self):
        return self.locked

    @contextlib.contextmanager
    def open_exact(self, item, collection):
        assert item == ITEM and collection == COLLECTION
        self.reads += 1
        self.locked = False
        try:
            self.during_open()
            if self.fail:
                raise RuntimeError(CANARY)
            yield ops.Material(CANARY, frozenset(self.visible_items),
                               frozenset(self.visible_collections), self.permissions)
        finally:
            self.locked = self.cleanup_ok
            if self.cleanup_raises:raise RuntimeError(CANARY)


class SyntheticConsumer:
    target_sha256 = hashlib.sha256(b'EXPLICIT-SYNTHETIC-DESTINATION').hexdigest()

    def __init__(self, callback):self.callback = callback
    def __call__(self, token):return self.callback(token)


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.ledger = Path(self.tmp.name)/'ledger'
        self.ledger.mkdir(mode=0o700)
        self.now = 1000
        self.caller_key = secrets.token_bytes(32)
        self.issuer_key = secrets.token_bytes(32)
        self.authority = ops.Authority(self.issuer_key, {'pilot':self.caller_key},
                                       self.ledger, clock=lambda:self.now)
        self.scope = ops.Scope('pilot', 'synthetic-profile', ITEM, COLLECTION, 'synthetic-read',
                               SyntheticConsumer.target_sha256)
        self.provider = SyntheticProvider()
        self.calls = 0
        self.executor = ops.Executor(self.authority, self.scope, self.provider, SyntheticConsumer(self.consume),
                                     enabled=True)

    def tearDown(self):
        self.authority.close()
        self.tmp.cleanup()

    def consume(self, token):
        self.assertEqual(token, CANARY)
        self.calls += 1

    def credentials(self):
        grant = self.authority.issue(self.scope, lifetime=30)
        return grant, ops.caller_proof(self.caller_key, grant)

    def run_request(self, **kwargs):
        grant, proof = self.credentials()
        return self.executor.execute(grant, proof, **kwargs)

    def test_success_consumes_privately_and_reports_only_fixed_booleans(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            report = self.run_request()
        self.assertEqual(report, {'status':'verified', 'code':'private_read_verified',
                                 'parent_locked':True, 'external_attempted':True})
        self.assertEqual((self.provider.reads, self.calls), (1, 1))
        self.assertEqual(out.getvalue()+err.getvalue(), '')
        self.assertNotIn(CANARY, json.dumps(report))

    def test_disabled_is_default_and_does_not_touch_provider(self):
        self.executor = ops.Executor(self.authority, self.scope, self.provider, self.consume)
        self.assertEqual(self.run_request()['code'], 'executor_disabled')
        self.assertEqual(self.provider.reads, 0)

    def test_wrong_consumer_destination_is_rejected_before_secret_read(self):
        class WrongConsumer(SyntheticConsumer):target_sha256 = 'f'*64
        self.executor.consumer = WrongConsumer(self.consume)
        self.assertEqual(self.run_request()['code'], 'authorization_denied')
        self.assertEqual((self.provider.reads,self.calls), (0,0))

    def test_forged_grant_and_proof_never_touch_provider(self):
        grant, proof = self.credentials()
        variants = [(dataclasses.replace(grant, signature=b'x'*32), proof),
                    (grant, b'x'*32),
                    (dataclasses.replace(grant, payload=b'garbage'), proof)]
        for g, p in variants:
            self.assertEqual(self.executor.execute(g, p)['code'], 'authorization_denied')
        self.assertEqual(self.provider.reads, 0)

    def test_valid_grant_for_wrong_profile_item_collection_or_operation_rejected(self):
        for field, value in [('caller','other'), ('profile','other'),
                             ('item_id', COLLECTION), ('collection_id', ITEM),
                             ('target_sha256','f'*64), ('operation','write')]:
            scope = dataclasses.replace(self.scope, **{field:value})
            if field == 'caller':
                with self.assertRaises(ops.Denied):self.authority.issue(scope)
                continue
            grant = self.authority.issue(scope)
            self.assertEqual(self.executor.execute(grant, ops.caller_proof(self.caller_key, grant))['code'],
                             'authorization_denied')
        self.assertEqual(self.provider.reads, 0)

    def test_expired_future_and_revoked_authorizations_fail(self):
        grant, proof = self.credentials()
        self.now += 31
        self.assertEqual(self.executor.execute(grant, proof)['code'], 'authorization_denied')
        grant, proof = self.credentials()
        self.now -= 1
        self.assertEqual(self.executor.execute(grant, proof)['code'], 'authorization_denied')
        self.now += 1
        self.authority.revoke('pilot')
        self.assertEqual(self.executor.execute(grant, proof)['code'], 'authorization_denied')
        self.assertEqual(self.provider.reads, 0)

    def test_replay_is_burned_even_if_provider_fails(self):
        grant, proof = self.credentials()
        self.provider.fail = True
        first = self.executor.execute(grant, proof)
        self.assertEqual(first['code'], 'private_provider_failed')
        self.assertNotIn(CANARY, json.dumps(first))
        self.provider.fail = False
        self.assertEqual(self.executor.execute(grant, proof)['code'], 'authorization_denied')
        self.assertEqual(self.provider.reads, 1)

    def test_replay_survives_authority_restart(self):
        grant, proof = self.credentials()
        self.executor.execute(grant, proof)
        self.authority.close()
        self.authority = ops.Authority(self.issuer_key, {'pilot':self.caller_key},
                                       self.ledger, clock=lambda:self.now)
        other = ops.Executor(self.authority, self.scope, self.provider, SyntheticConsumer(self.consume), enabled=True)
        self.assertEqual(other.execute(grant, proof)['code'], 'authorization_denied')
        self.assertEqual(len(list(self.ledger.iterdir())), 1)

    def test_expiry_or_revocation_during_unlock_prevents_external_request(self):
        for mutate in (lambda:setattr(self, 'now', self.now+31),
                       lambda:self.authority.revoke('pilot')):
            grant, proof = self.credentials()
            self.provider.during_open = mutate
            report = self.executor.execute(grant, proof)
            self.assertEqual(report['code'], 'authorization_denied')
            self.assertTrue(report['parent_locked'])
            self.assertEqual(self.calls, 0)
            if self.authority.is_revoked('pilot'):break

    def test_visibility_and_unknown_permissions_fail_closed(self):
        for items, collections, permission in [({ITEM,COLLECTION},{COLLECTION},True),
                                              ({ITEM},{COLLECTION,ITEM},True),
                                              ({ITEM},{COLLECTION},None),
                                              ({ITEM},{COLLECTION},False)]:
            self.provider.visible_items = items
            self.provider.visible_collections = collections
            self.provider.permissions = permission
            report = self.run_request()
            self.assertEqual(report['code'], 'visibility_or_permission_denied')
            self.assertTrue(report['parent_locked'])
        self.assertEqual(self.calls, 0)

    def test_parent_unlocked_prevents_provider_read(self):
        self.provider.locked = False
        self.assertEqual(self.run_request()['code'], 'parent_not_locked')
        self.assertEqual(self.provider.reads, 0)

    def test_cleanup_failure_overrides_consumer_success(self):
        self.provider.cleanup_ok = False
        report = self.run_request()
        self.assertEqual(report['status'], 'blocked')
        self.assertEqual(report['code'], 'cleanup_unverified')
        self.assertFalse(report['parent_locked'])

    def test_consumer_exception_is_opaque_and_never_retried(self):
        def fail(token):
            self.calls += 1
            raise RuntimeError(token)
        self.executor.consumer = SyntheticConsumer(fail)
        report = self.run_request()
        self.assertEqual(report['code'], 'external_outcome_unknown')
        self.assertEqual(self.calls, 1)
        self.assertTrue(report['parent_locked'])
        self.assertNotIn(CANARY, json.dumps(report))

    def test_cleanup_exception_cannot_promote_success_even_when_locked(self):
        self.provider.cleanup_raises = True
        report = self.run_request()
        self.assertEqual(report['code'], 'cleanup_unverified')
        self.assertTrue(report['parent_locked'])
        self.assertEqual(self.calls, 1)
        self.assertNotIn(CANARY, json.dumps(report))

    def test_consumer_interruption_still_cleans_provider_and_burns_grant(self):
        def interrupted(token):raise KeyboardInterrupt(token)
        self.executor.consumer = SyntheticConsumer(interrupted)
        grant, proof = self.credentials()
        report = self.executor.execute(grant, proof)
        self.assertEqual(report['code'], 'external_outcome_unknown')
        self.assertTrue(report['parent_locked'])
        self.assertEqual(self.executor.execute(grant, proof)['code'], 'authorization_denied')

    def test_same_executor_busy_does_not_overlap_provider(self):
        entered, release = threading.Event(), threading.Event()
        self.provider.during_open = lambda:(entered.set(), release.wait(5))
        grant, proof = self.credentials()
        reports = []
        thread = threading.Thread(target=lambda:reports.append(self.executor.execute(grant, proof)))
        thread.start()
        try:
            self.assertTrue(entered.wait(5))
            other_grant, other_proof = self.credentials()
            self.assertEqual(self.executor.execute(other_grant, other_proof)['code'], 'executor_busy')
            self.assertEqual(self.provider.reads, 1)
        finally:release.set();thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(reports[0]['status'], 'verified')

    def test_invalid_literal_id_and_wildcard_are_not_repaired(self):
        for value in [' '+ITEM, ITEM+' ', '*', 'title']:
            with self.assertRaises(ops.Denied):
                self.authority.issue(dataclasses.replace(self.scope, item_id=value))

    def test_grant_representation_does_not_expose_capability(self):
        grant, _ = self.credentials()
        self.executor.execute(grant, ops.caller_proof(self.caller_key, grant))
        self.assertNotIn('payload=', repr(grant))
        self.assertNotIn('signature=', repr(grant))
        for path in self.ledger.iterdir():self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_caller_keys_cannot_alias_each_other_or_issuer(self):
        with self.assertRaises(ops.Denied):
            ops.Authority(self.issuer_key,{'pilot':self.caller_key,'other':self.caller_key},self.ledger)
        with self.assertRaises(ops.Denied):
            ops.Authority(self.issuer_key,{'pilot':self.issuer_key},self.ledger)

    def test_ledger_symlink_or_public_directory_rejected(self):
        link = Path(self.tmp.name)/'link';link.symlink_to(self.ledger)
        for directory in [link, Path(self.tmp.name)]:
            if directory == Path(self.tmp.name):directory.chmod(0o755)
            with self.assertRaises(ops.Denied):
                ops.Authority(secrets.token_bytes(32), {'pilot':self.caller_key}, directory)

    def test_two_authorities_race_for_one_nonce_only_one_claims(self):
        # Same trusted key and custody dir; O_EXCL is the cross-instance admission boundary.
        key = secrets.token_bytes(32)
        a = ops.Authority(key, {'pilot':self.caller_key}, self.ledger, clock=lambda:self.now)
        b = ops.Authority(key, {'pilot':self.caller_key}, self.ledger, clock=lambda:self.now)
        grant = a.issue(self.scope);proof = ops.caller_proof(self.caller_key, grant)
        barrier = threading.Barrier(2);results = []
        def claim(authority):
            barrier.wait()
            try:authority.claim(grant, proof, self.scope);results.append(True)
            except ops.Denied:results.append(False)
        threads = [threading.Thread(target=claim,args=(x,)) for x in [a,b]]
        try:
            for t in threads:t.start()
            for t in threads:t.join(5);self.assertFalse(t.is_alive())
            self.assertEqual(sorted(results), [False,True])
        finally:a.close();b.close()


class HTTPSFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(dir=SCRATCH)
        root = Path(cls.tmp.name)
        cls.cert = root/'cert.pem';key = root/'key.pem'
        cfg = root/'openssl.cnf'
        cfg.write_text('[req]\ndistinguished_name=dn\nx509_extensions=ext\nprompt=no\n[dn]\nCN=localhost\n[ext]\nsubjectAltName=DNS:localhost\nbasicConstraints=critical,CA:TRUE\n')
        env = os.environ.copy()
        p = subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
                            '-keyout',str(key),'-out',str(cls.cert),'-config',str(cfg)],
                           capture_output=True,env=env,timeout=30)
        if p.returncode:raise RuntimeError('synthetic_tls_fixture_generation_failed')
        cls.mode = 'success';cls.requests = 0;cls.auth_matches = False
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):pass
            def do_GET(self):
                cls.requests += 1
                cls.auth_matches = self.headers.get('Authorization') == 'Bearer '+CANARY
                body = BODY if cls.mode=='success' else CANARY.encode()
                if cls.mode=='oversize':body = b'x'*70000
                status = 302 if cls.mode=='redirect' else 200
                self.send_response(status)
                if status==302:self.send_header('Location','https://wrong.example.com/')
                self.send_header('Content-Length',str(len(body)));self.end_headers()
                try:self.wfile.write(body)
                except (BrokenPipeError,ssl.SSLError,ConnectionResetError):pass
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.server.daemon_threads = False
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(cls.cert,key)
        cls.server.socket = context.wrap_socket(cls.server.socket,server_side=True)
        cls.thread = threading.Thread(target=cls.server.serve_forever);cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join(5);cls.tmp.cleanup()

    def setUp(self):
        self.__class__.mode = 'success';self.__class__.requests = 0
        self.__class__.auth_matches = False
        self.url = 'https://localhost:'+str(self.server.server_port)+'/synthetic/read'
        self.consumer = ops.FixedHTTPSRead(self.url, hashlib.sha256(BODY).hexdigest(),
                                          context=ssl.create_default_context(cafile=str(self.cert)))

    def test_real_tls_authorization_and_readback(self):
        self.assertIsNone(self.consumer(CANARY))
        self.assertTrue(self.auth_matches)
        self.assertEqual(self.requests, 1)

    def test_entire_private_core_with_real_tls_and_no_canary_output(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as tmp:
            ledger = Path(tmp)/'ledger';ledger.mkdir(mode=0o700)
            key = secrets.token_bytes(32)
            authority = ops.Authority(secrets.token_bytes(32), {'pilot':key}, ledger)
            provider = SyntheticProvider()
            scope = ops.Scope('pilot','synthetic-profile',ITEM,COLLECTION,'synthetic-read',
                              self.consumer.target_sha256)
            executor = ops.Executor(authority,scope,provider,self.consumer,enabled=True)
            out, err = io.StringIO(), io.StringIO()
            try:
                grant = authority.issue(scope)
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    report = executor.execute(grant, ops.caller_proof(key,grant))
                self.assertEqual(report['status'], 'verified')
                self.assertTrue(report['parent_locked'])
                self.assertEqual(self.requests, 1)
                self.assertTrue(self.auth_matches)
                self.assertNotIn(CANARY,out.getvalue()+err.getvalue()+json.dumps(report))
                self.assertEqual(executor.execute(grant,ops.caller_proof(key,grant))['code'],
                                 'authorization_denied')
                self.assertEqual(self.requests, 1)
            finally:authority.close()

    def test_entire_core_rejects_canary_response_without_export_or_retry(self):
        self.__class__.mode = 'mismatch'
        with tempfile.TemporaryDirectory(dir=SCRATCH) as tmp:
            ledger = Path(tmp)/'ledger';ledger.mkdir(mode=0o700)
            key = secrets.token_bytes(32)
            authority = ops.Authority(secrets.token_bytes(32),{'pilot':key},ledger)
            scope = ops.Scope('pilot','synthetic-profile',ITEM,COLLECTION,'synthetic-read',
                              self.consumer.target_sha256)
            executor = ops.Executor(authority,scope,SyntheticProvider(),self.consumer,enabled=True)
            try:
                grant = authority.issue(scope)
                report = executor.execute(grant,ops.caller_proof(key,grant))
                self.assertEqual(report['code'],'external_outcome_unknown')
                self.assertTrue(report['parent_locked'])
                self.assertNotIn(CANARY,json.dumps(report))
                self.assertEqual(self.requests,1)
            finally:authority.close()

    def test_entire_core_rejects_wrong_https_origin_before_request(self):
        other = ops.FixedHTTPSRead('https://wrong.example.com/read', hashlib.sha256(BODY).hexdigest())
        with tempfile.TemporaryDirectory(dir=SCRATCH) as tmp:
            ledger = Path(tmp)/'ledger';ledger.mkdir(mode=0o700)
            key = secrets.token_bytes(32)
            authority = ops.Authority(secrets.token_bytes(32),{'pilot':key},ledger)
            scope = ops.Scope('pilot','synthetic-profile',ITEM,COLLECTION,'synthetic-read',
                              other.target_sha256)
            provider = SyntheticProvider()
            executor = ops.Executor(authority,scope,provider,self.consumer,enabled=True)
            try:
                grant = authority.issue(scope)
                report = executor.execute(grant,ops.caller_proof(key,grant))
                self.assertEqual(report['code'],'authorization_denied')
                self.assertEqual(provider.reads,0)
                self.assertEqual(self.requests,0)
            finally:authority.close()

    def test_redirect_body_mismatch_and_byte_limit_are_not_returned(self):
        for mode in ['redirect','mismatch','oversize']:
            self.__class__.mode = mode
            with self.assertRaises(ops.Denied) as caught:self.consumer(CANARY)
            self.assertNotIn(CANARY, str(caught.exception))
        self.assertEqual(self.requests, 3)  # No redirect follow-up or automatic retry.

    def test_untrusted_tls_fails_without_request(self):
        consumer = ops.FixedHTTPSRead(self.url, hashlib.sha256(BODY).hexdigest())
        with self.assertRaises(ops.Denied):consumer(CANARY)
        self.assertEqual(self.requests, 0)

    def test_insecure_tls_context_http_userinfo_query_and_fragments_rejected(self):
        # Negative fixture only: unsafe TLS must be rejected before connection.
        with self.assertRaises(ops.Denied):
            ops.FixedHTTPSRead(self.url, hashlib.sha256(BODY).hexdigest(), context=ssl._create_unverified_context())
        for url in ['http://localhost/read','https://user:pass@localhost/read',
                    self.url+'?token=x',self.url+'#x',self.url+'/../write']:
            with self.assertRaises(ops.Denied):ops.FixedHTTPSRead(url, hashlib.sha256(BODY).hexdigest())

    def test_header_injection_rejected_before_connection(self):
        with self.assertRaises(ops.Denied):self.consumer(CANARY+'\r\nX-Evil: 1')
        self.assertEqual(self.requests, 0)


if __name__ == '__main__':unittest.main()
