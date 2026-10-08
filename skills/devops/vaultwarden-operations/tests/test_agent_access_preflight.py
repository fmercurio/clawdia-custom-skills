"""Real owned metadata children and policy tests; no vault login or secret access."""
import copy
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/agent_access_preflight.py'
SPEC = importlib.util.spec_from_file_location('access_preflight', SCRIPT)
ops = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ops)
EXAMPLE = json.loads((ROOT/'templates/agent-access-policy.example.json').read_text())
NOW = dt.datetime(2026, 10, 8, tzinfo=dt.timezone.utc)


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = copy.deepcopy(EXAMPLE)

    def rejects(self, policy):
        with self.assertRaises(ops.GateError):
            ops.validate_policy(policy)

    def test_example_is_valid_but_disabled_and_expired(self):
        report = ops.inspect_policy(self.policy, NOW)
        self.assertFalse(report['agent_access_enabled'])
        self.assertIn('policy_disabled', report['blocking_codes'])
        self.assertIn('policy_expired', report['blocking_codes'])

    def test_valid_policy_and_locked_cli_never_authorize_secret_use(self):
        self.policy.update(enabled=True, expires_at='2026-10-09T00:00:00Z')
        report = ops.inspect_policy(self.policy, NOW, {'status':'locked',
            'serverUrl':self.policy['server_origin'], 'userId':self.policy['account_id']})
        self.assertTrue(report['parent_locked'])
        self.assertTrue(report['account_matches'])
        self.assertTrue(report['server_matches'])
        self.assertFalse(report['caller_authenticated'])
        self.assertFalse(report['secret_executor_implemented'])
        self.assertFalse(report['agent_access_enabled'])
        self.assertIn('private_executor_pending', report['blocking_codes'])

    def test_wrong_server_identity_and_unlocked_or_unauthenticated_fail(self):
        for status in ('unlocked','unauthenticated'):
            report = ops.inspect_policy(self.policy, NOW, {'status':status,
                'serverUrl':'https://wrong.example.com', 'userId':'wrong'})
            for code in ('parent_not_locked','server_mismatch','account_mismatch'):
                self.assertIn(code, report['blocking_codes'])

    def test_no_duplicate_json_keys_or_unbounded_input(self):
        for body in (b'{"schema":1,"schema":1}', b'x'*(ops.MAX_BYTES+1)):
            with self.assertRaises(ops.GateError):ops.parse_json(body)

    def test_type_coercion_and_unknown_keys_rejected(self):
        for key, value in [('schema',True),('enabled',1),('scopes','scope')]:
            policy=copy.deepcopy(self.policy);policy[key]=value;self.rejects(policy)
        self.policy['session_token']='EXPLICIT_SYNTHETIC_CANARY';self.rejects(self.policy)

    def test_human_account_arbitrary_consumer_and_writes_rejected(self):
        self.policy['account_kind']='human';self.rejects(self.policy)
        for key,value in [('consumer','arbitrary_shell'),('operation','create')]:
            policy=copy.deepcopy(EXAMPLE);policy['scopes'][0][key]=value;self.rejects(policy)

    def test_literal_item_id_preserved_and_invalid_not_repaired(self):
        valid=self.policy['scopes'][0]['item_id']
        for value in (' '+valid, valid+' ', valid.upper().replace('0000','ABCD',1), 'title'):
            policy=copy.deepcopy(self.policy);policy['scopes'][0]['item_id']=value;self.rejects(policy)
        ops.validate_policy(self.policy)
        self.assertEqual(self.policy['scopes'][0]['item_id'],valid)

    def test_wildcard_duplicate_and_oversized_scopes_rejected(self):
        policy=copy.deepcopy(self.policy);policy['scopes'][0]['profile']='*';self.rejects(policy)
        policy=copy.deepcopy(self.policy);policy['scopes']*=2;self.rejects(policy)
        policy=copy.deepcopy(self.policy);policy['scopes']*=33;self.rejects(policy)

    def test_https_origin_without_credentials_query_or_path(self):
        for origin in ('http://vault.example.com','https://user:canary@vault.example.com',
                       'https://vault.example.com/path','https://vault.example.com/?canary',
                       'https://vault.example.com#fragment'):
            policy=copy.deepcopy(self.policy);policy['server_origin']=origin;self.rejects(policy)

    def test_expiry_requires_utc_and_path_requires_absolute(self):
        for expiry in ('invalid','2026-10-09T00:00:00','2026-10-09T00:00:00-03:00'):
            policy=copy.deepcopy(self.policy);policy['expires_at']=expiry;self.rejects(policy)
        self.policy['cli_state_directory']='relative';self.rejects(self.policy)

    def test_readback_contains_no_identity_selector_or_canary(self):
        self.policy['account_id']='EXPLICIT_SYNTHETIC_CANARY'
        self.policy['scopes'][0]['profile']='EXPLICIT_SYNTHETIC_PROFILE_CANARY'
        report=ops.inspect_policy(self.policy, NOW, {'status':'locked','userId':'CANARY'})
        encoded=json.dumps(report)
        for token in ('CANARY',self.policy['server_origin'],self.policy['scopes'][0]['item_id']):
            self.assertNotIn(token, encoded)

    def test_cli_example_runs_and_reports_blocked_without_secrets(self):
        p=subprocess.run([sys.executable,'-B',str(SCRIPT),'--policy',str(ROOT/'templates/agent-access-policy.example.json')],capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,2)
        report=json.loads(p.stdout)
        self.assertEqual(report['status'],'blocked')
        self.assertFalse(report['agent_access_enabled'])
        self.assertEqual(p.stderr,'')


class OwnedChildTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()

    def fixture(self, body):
        binary=self.root/'fixture-cli'
        # Executable belongs only to this test; never a live credential connector.
        binary.write_text('#!'+sys.executable+'\n'+body)
        binary.chmod(0o700)
        return str(binary)

    def test_protected_policy_rejects_symlink_permissions_and_fifo(self):
        target=self.root/'policy';target.write_text(json.dumps(EXAMPLE));target.chmod(0o644)
        with self.assertRaises(ops.GateError):ops.read_policy(target,protected=True)
        target.chmod(0o600);self.assertEqual(ops.read_policy(target,True),EXAMPLE)
        link=self.root/'link';link.symlink_to(target)
        with self.assertRaises(ops.GateError):ops.read_policy(link,True)
        fifo=self.root/'fifo';os.mkfifo(fifo)
        with self.assertRaises(ops.GateError):ops.read_policy(fifo,True)

    def test_dedicated_directory_permissions_and_symlink_gate(self):
        state=self.root/'state';state.mkdir(mode=0o700);ops.validate_state_path(str(state))
        state.chmod(0o755)
        with self.assertRaises(ops.GateError):ops.validate_state_path(str(state))
        state.chmod(0o700);link=self.root/'link';link.symlink_to(state)
        with self.assertRaises(ops.GateError):ops.validate_state_path(str(link))

    def test_real_cli_child_gets_status_only_and_no_secret_or_proxy_environment(self):
        binary=self.fixture("import os,sys,json\nassert sys.argv[1:]==['status','--nointeraction']\nassert 'BW_SESSION' not in os.environ and 'HTTPS_PROXY' not in os.environ\nprint(json.dumps({'status':'unauthenticated'}))\n")
        from unittest.mock import patch
        with patch.dict(os.environ,{'BW_SESSION':'EXPLICIT_SYNTHETIC_CANARY','HTTPS_PROXY':'canary'}):
            result=ops.bounded_status(binary,str(self.root),timeout=5)
        self.assertEqual(result,{'status':'unauthenticated'})

    def test_child_failure_never_replays_stderr_canary(self):
        binary=self.fixture("import sys\nsys.stderr.write('EXPLICIT_SYNTHETIC_CANARY');sys.exit(1)\n")
        with self.assertRaisesRegex(ops.GateError,'^status_failed$') as error:
            ops.bounded_status(binary,str(self.root),timeout=5)
        self.assertNotIn('CANARY',str(error.exception))

    def test_limits_stdout_and_stderr_before_json_parse(self):
        for fd in (1,2):
            binary=self.fixture("import os\nos.write("+str(fd)+",b'x'*70000)\n")
            with self.assertRaisesRegex(ops.GateError,'^status_byte_limit$'):
                ops.bounded_status(binary,str(self.root),timeout=5)

    def test_timeout_reaps_owned_child(self):
        marker=self.root/'pid'
        binary=self.fixture('import os,time\nopen('+repr(str(marker))+',"w").write(str(os.getpid()))\ntime.sleep(30)\n')
        with self.assertRaisesRegex(ops.GateError,'^status_timeout$'):
            ops.bounded_status(binary,str(self.root),timeout=1)
        self.assertTrue(marker.is_file())
        with self.assertRaises(ProcessLookupError):os.kill(int(marker.read_text()),0)


if __name__=='__main__':
    unittest.main()
