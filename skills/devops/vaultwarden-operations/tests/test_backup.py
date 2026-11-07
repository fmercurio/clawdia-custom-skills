"""Offline/owned-child tests only. No credential reads or live mutations."""
import copy
import contextlib
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('backup_under_test', Path(__file__).resolve().parents[1]/'scripts'/'backup.py')
ops = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ops)
CONFIG = {'image': 'vaultwarden/server:synthetic@sha256:'+'a'*64, 'max_archive_bytes': 10485760, 'max_expanded_bytes': 20971520, 'max_members': 1000, 'resource_uuid': 'explicit-synthetic-resource', 'state_root': 'unused-test-state', 'data_path': '/synthetic/encrypted-data', 'ssh_argv': ['ssh','explicit-synthetic-host'], 'age_bin': __import__('shutil').which('age'), 'age_recipient': None}
# Generate an ephemeral synthetic key in memory, never persist/print its private part.
KEYGEN = __import__('shutil').which('age-keygen')
if CONFIG['age_bin'] and KEYGEN:
    generated = subprocess.run([KEYGEN], capture_output=True, text=True, check=True)
    recipient = subprocess.run([KEYGEN, '-y'], input=generated.stdout, capture_output=True, text=True, check=True).stdout.strip()
    CONFIG['age_recipient'] = recipient
    del generated
SCRATCH = os.environ.get('TMPDIR') or tempfile.gettempdir()


def payloads(view=False):
    db = sqlite3.connect(':memory:')
    if view:
        db.execute('CREATE VIEW users AS SELECT 1 AS id')
    else:
        db.execute('CREATE TABLE users(id TEXT)')
    result = {'db.sqlite3': db.serialize(), 'rsa_key.pem': b'EXPLICIT_SYNTHETIC_KEY_FIXTURE', '.vaultwarden-volume-ready': b'ready', '.vaultwarden-persistence-probe': b'synthetic-persistence'}
    db.close()
    return result


def bundle(values=None, extra=None, manifest_change=None, global_pax=None, special=None):
    values = payloads() if values is None else values
    manifest = {'schema': 1, 'image': CONFIG['image'], 'files': {name: {'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()} for name, body in values.items()}}
    if manifest_change:
        manifest_change(manifest)
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode='w:', format=tarfile.PAX_FORMAT, pax_headers=global_pax) as archive:
        metadata = json.dumps(manifest).encode()
        item = tarfile.TarInfo(ops.MANIFEST); item.size = len(metadata)
        archive.addfile(item, io.BytesIO(metadata))
        for name, body in list(values.items()) + (extra or []):
            item = tarfile.TarInfo(name); item.size = len(body)
            archive.addfile(item, io.BytesIO(body))
        if special:
            archive.addfile(special)
    return gzip.compress(raw.getvalue(), mtime=0)


class ArchiveTests(unittest.TestCase):
    def rejects(self, body, cfg=None):
        with self.assertRaises(Exception):
            ops.validate_archive(body, cfg or CONFIG)

    def test_valid_bundle_and_native_database(self):
        _, manifest, report = ops.validate_archive(bundle(), CONFIG)
        self.assertEqual(report['payload_files'], len(payloads()))
        self.assertEqual(report['sqlite_integrity'], 'ok')
        self.assertEqual(report['users'], 0)
        self.assertEqual(set(manifest['files']), set(payloads()))

    def test_valid_long_path_pax(self):
        data = payloads(); data['attachments/'+'a'*150] = b'synthetic-attachment'
        _, manifest, _ = ops.validate_archive(bundle(data), CONFIG)
        self.assertIn('attachments/'+'a'*150, manifest['files'])

    def test_real_wal_snapshot_uses_validation_copy_only(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH, prefix='vw-wal-tests-') as directory:
            source = sqlite3.connect(str(Path(directory)/'synthetic.sqlite3'))
            source.execute('PRAGMA journal_mode=WAL');source.execute('CREATE TABLE users(id TEXT)');source.execute("INSERT INTO users VALUES ('explicit-synthetic-row')");source.commit()
            memory = sqlite3.connect(':memory:');source.backup(memory)
            original = memory.serialize();memory.close();source.close()
            self.assertEqual(original[18:20], b'\x02\x02')
            data = payloads();data['db.sqlite3'] = original
            compressed = bundle(data)
            raw,manifest,evidence = ops.validate_archive(compressed, CONFIG)
            with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as archive:
                restored_bytes = archive.extractfile('db.sqlite3').read()
            self.assertEqual(restored_bytes, original)
            self.assertEqual(manifest['files']['db.sqlite3']['sha256'], hashlib.sha256(original).hexdigest())
            self.assertEqual(evidence['users'], 1)

    def test_rejects_traversal_absolute_and_noncanonical_paths(self):
        for path in ('../escape', '/escape', 'a//b', './escape', 'a/../b', 'a\\b'):
            with self.subTest(path=path):
                data = payloads(); data[path] = b'fixture'
                self.rejects(bundle(data))

    def test_rejects_duplicate_members(self):
        self.rejects(bundle(extra=[('db.sqlite3', payloads()['db.sqlite3'])]))

    def test_rejects_symlink_hardlink_device_and_directory(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.DIRTYPE):
            item = tarfile.TarInfo('unsafe'); item.type = kind; item.linkname = '../outside'
            self.rejects(bundle(special=item))

    def test_rejects_parent_file_collision_in_both_orders(self):
        for names in (('a', 'a/b'), ('a/b', 'a')):
            values = payloads()
            for name in names: values[name] = b'fixture'
            self.rejects(bundle(values))

    def test_rejects_manifest_checksum_size_extra_and_missing(self):
        for mutate in (lambda m: m['files']['db.sqlite3'].update(sha256='0'*64), lambda m: m['files']['db.sqlite3'].update(bytes=1), lambda m: m['files'].pop('db.sqlite3'), lambda m: m['files'].update(extra={'bytes': 0, 'sha256': '0'*64})):
            self.rejects(bundle(manifest_change=mutate))

    def test_rejects_wrong_image(self):
        self.rejects(bundle(manifest_change=lambda m: m.update(image='different-image')))

    def test_rejects_invalid_database_and_users_view(self):
        data = payloads(); data['db.sqlite3'] = b'NOT_A_DATABASE'
        self.rejects(bundle(data))
        self.rejects(bundle(payloads(view=True)))

    def test_rejects_missing_recovery_key(self):
        data = payloads(); del data['rsa_key.pem']
        self.rejects(bundle(data))

    def test_rejects_global_pax(self):
        self.rejects(bundle(global_pax={'comment': 'untrusted-global'}))

    def test_rejects_oversized_pax_and_declared_member(self):
        item = tarfile.TarInfo('pax'); item.pax_headers = {'path': 'a'*70000}
        self.rejects(bundle(special=item))
        item = tarfile.TarInfo('huge'); item.size = CONFIG['max_expanded_bytes']+1
        hostile_header = item.tobuf(format=tarfile.USTAR_FORMAT)
        self.rejects(gzip.compress(hostile_header+gzip.decompress(bundle())))

    def test_rejects_gzip_truncation_crc_and_concatenation(self):
        body = bundle()
        self.rejects(body[:-4])
        damaged = bytearray(body); damaged[-8] ^= 1
        self.rejects(bytes(damaged))
        self.rejects(body+gzip.compress(b'extra'))

    def test_rejects_tar_trailer_garbage(self):
        raw = gzip.decompress(bundle())
        self.rejects(gzip.compress(raw+b'x'*512))

    def test_rejects_byte_expansion_and_member_limits(self):
        body = bundle()
        for override in ({'max_archive_bytes': 1}, {'max_expanded_bytes': 512}, {'max_members': 2}):
            cfg = copy.deepcopy(CONFIG); cfg.update(override)
            self.rejects(body, cfg)

    def test_rejects_duplicate_json_keys(self):
        with self.assertRaises(ops.GateError):
            json.loads('{"schema":1,"schema":1}', object_pairs_hook=ops.unique_object)


class ChildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=SCRATCH, prefix='vw-backup-tests-')
        self.addCleanup(self.temp.cleanup)
        cfg = copy.deepcopy(CONFIG); cfg['state_root'] = self.temp.name
        self.operator = ops.Operator(cfg)

    def test_real_bounded_child(self):
        value = self.operator.read_bounded([sys.executable, '-I', '-B', '-c', "import os;os.write(1,b'x'*5000)"], 10000, 5)
        self.assertEqual(value, b'x'*5000)

    def test_bounded_limit_and_timeout_join_children(self):
        for code, limit, timeout in (("import os;os.write(1,b'x'*5000)", 10, 5), ('import time;time.sleep(5)', 100, 0.1)):
            children = []; real = subprocess.Popen
            def tracked(*args, **kwargs):
                child = real(*args, **kwargs); children.append(child); return child
            with patch.object(ops.subprocess, 'Popen', tracked), self.assertRaises(ops.GateError):
                self.operator.read_bounded([sys.executable, '-I', '-B', '-c', code], limit, timeout)
            self.assertTrue(children)
            self.assertTrue(all(child.poll() is not None for child in children))

    def test_child_stderr_canary_is_not_exposed(self):
        with self.assertRaises(ops.GateError) as error:
            self.operator.read_bounded([sys.executable, '-I', '-B', '-c', "import sys;sys.stderr.write('CANARY_NOT_A_CREDENTIAL');sys.exit(1)"], 100, 5)
        self.assertEqual(str(error.exception), 'bounded_reader_child_failed')
        self.assertNotIn('CANARY', str(error.exception))

    @unittest.skipUnless(CONFIG['age_bin'] and KEYGEN, 'requires age and age-keygen')
    def test_real_age_pipeline_encrypts_owned_synthetic_stream(self):
        target = Path(self.temp.name)/'synthetic.age'
        self.operator.encrypt_snapshot([sys.executable, '-I', '-B', '-c', "import os;os.write(1,b'EXPLICIT_SYNTHETIC_PAYLOAD')"], target, timeout=5)
        body = target.read_bytes()
        self.assertTrue(body.startswith(b'age-encryption.org/v1'))
        self.assertNotIn(b'EXPLICIT_SYNTHETIC_PAYLOAD', body)

    @unittest.skipUnless(CONFIG['age_bin'] and KEYGEN, 'requires age and age-keygen')
    def test_age_timeout_and_launch_error_join_all_children(self):
        for missing_binary in (False, True):
            children = []; real = subprocess.Popen
            def tracked(*args, **kwargs):
                child = real(*args, **kwargs); children.append(child); return child
            if missing_binary: self.operator.cfg['age_bin'] = str(Path(self.temp.name)/'does-not-exist')
            target = Path(self.temp.name)/('launch-failure.age' if missing_binary else 'timeout.age')
            with patch.object(ops.subprocess, 'Popen', tracked), self.assertRaises(Exception):
                self.operator.encrypt_snapshot([sys.executable, '-I', '-B', '-c', 'import time;time.sleep(5)'], target, timeout=0.1)
            self.assertTrue(children)
            self.assertTrue(all(child.poll() is not None for child in children))


class RecoveryTests(unittest.TestCase):
    def test_snapshot_failure_recovers_exact_application_before_rethrow(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH, prefix='vw-recovery-tests-') as directory:
            cfg = copy.deepcopy(CONFIG); cfg['state_root'] = directory
            class Fake(ops.Operator):
                def __init__(self): super().__init__(cfg); self.running = True; self.actions = []
                def check(self): return {}
                def api(self, suffix='', method='GET', data=None):
                    if suffix == '': return {'status': 'exited' if not self.running else 'running:healthy'}
                    self.actions.append(suffix)
                    if suffix == '/stop': self.running = False
                    elif suffix == '/start': self.running = True
                    else: raise AssertionError('unexpected endpoint')
                    return {}
                def state(self): return {'running': self.running, 'health': 'healthy' if self.running else None, 'image': cfg['image']}
                def encrypt_snapshot(self, *args, **kwargs): raise ops.GateError('injected_snapshot_failure')
            operator = Fake()
            with self.assertRaisesRegex(ops.GateError, 'injected_snapshot_failure'):
                operator.backup()
            self.assertEqual(operator.actions, ['/stop', '/start'])
            self.assertTrue(operator.running)
            self.assertFalse((Path(directory)/'last-backup.json').exists())

    def test_unobservable_docker_is_not_classified_as_stopped(self):
        operator = ops.Operator(copy.deepcopy(CONFIG))
        seen = []
        def inspect_code(code):
            seen.append(code)
            self.assertIn("if p.returncode:raise SystemExit('docker_inventory_unobservable')", code)
            raise ops.GateError('child_command_failed')
        operator.remote = inspect_code
        with self.assertRaises(ops.GateError): operator.state()
        self.assertEqual(len(seen), 1)

    def test_verified_inventory_absence_is_quiescent_without_fake_image(self):
        operator = ops.Operator(copy.deepcopy(CONFIG))
        def run_remote(code):
            output = io.StringIO()
            with patch.object(ops.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'unrelated-container\n', '')), contextlib.redirect_stdout(output):
                exec(compile(code, '<test-remote-state>', 'exec'), {})
            return output.getvalue().encode()
        operator.remote = run_remote
        state = operator.wait(False, timeout=1)
        self.assertEqual(state, {'running': False, 'health': None, 'image': None, 'present': False})

    def test_failed_docker_inventory_exec_cannot_return_absence(self):
        operator = ops.Operator(copy.deepcopy(CONFIG))
        def run_remote(code):
            output = io.StringIO()
            with patch.object(ops.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'CANARY_NOT_A_CREDENTIAL')), contextlib.redirect_stdout(output):
                exec(compile(code, '<test-remote-state>', 'exec'), {})
            return output.getvalue().encode()
        operator.remote = run_remote
        with self.assertRaises(SystemExit) as error: operator.state()
        self.assertEqual(str(error.exception), 'docker_inventory_unobservable')


class EntryPointTests(unittest.TestCase):
    def invoke(self, arguments):
        script=Path(__file__).resolve().parents[1]/'scripts'/'backup.py'
        child=subprocess.run([sys.executable,'-B',str(script),*arguments],capture_output=True,text=True,timeout=10)
        self.assertEqual(child.returncode,1)
        self.assertEqual(child.stderr,'')
        return json.loads(child.stdout)

    def test_mutations_require_explicit_apply_before_any_config_read(self):
        for action in ('backup','restore'):
            report=self.invoke(['--config','nonexistent-protected-fixture',action])
            self.assertEqual(report['gate'],'explicit_apply_required')
            self.assertTrue(report['no_automatic_retry'])

    def test_world_readable_config_rejected_before_credential_discovery(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as directory:
            target=Path(directory)/'config';target.write_text('EXPLICIT_SYNTHETIC_CANARY');target.chmod(0o644)
            report=self.invoke(['--config',str(target),'check'])
            self.assertEqual(report['gate'],'private_config_permissions')
            self.assertNotIn('CANARY',json.dumps(report))

    def test_oversized_private_config_rejected_before_json(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as directory:
            target=Path(directory)/'config';target.write_bytes(b'x'*65537);target.chmod(0o600)
            report=self.invoke(['--config',str(target),'check'])
            self.assertEqual(report['gate'],'private_config_limit')


if __name__ == '__main__':
    os.umask(0o077)
    unittest.main(verbosity=2)
