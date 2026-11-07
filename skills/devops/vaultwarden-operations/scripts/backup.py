#!/usr/bin/env python3
"""Candidate exact-resource backup/restore; explicit apply only. No agent-vault executor."""
import argparse
import ast
import datetime as dt
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import shlex
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request
import zlib
from typing import NoReturn

# Private configuration is supplied explicitly; no live state is shipped.
MANIFEST = 'backup-manifest.json'

class GateError(Exception):
    pass

def fail(gate) -> NoReturn:
    raise GateError(gate)

def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            fail('duplicate_json_key')
        result[key] = value
    return result

def safe_path(name):
    if not isinstance(name, str) or not name or len(name.encode('utf-8')) > 1024:
        fail('archive_path_invalid')
    p = PurePosixPath(name)
    if p.is_absolute() or str(p) != name or any(x in ('', '.', '..') for x in name.split('/')) or '\\' in name or '\x00' in name:
        fail('archive_path_invalid')
    return name

def validate_archive(compressed, cfg):
    deadline = time.monotonic() + 15
    if len(compressed) > cfg['max_archive_bytes']:
        fail('archive_compressed_limit')
    decoder = zlib.decompressobj(31)
    expanded = bytearray()
    for offset in range(0, len(compressed), 65536):
        if time.monotonic() > deadline:
            fail('archive_validation_timeout')
        chunk = compressed[offset:offset+65536]
        while chunk:
            remaining = cfg['max_expanded_bytes'] - len(expanded)
            piece = decoder.decompress(chunk, min(1048576, remaining + 1))
            expanded.extend(piece)
            if len(expanded) > cfg['max_expanded_bytes']:
                fail('archive_expansion_limit')
            chunk = decoder.unconsumed_tail
    if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        fail('gzip_incomplete_or_concatenated')
    expanded = bytes(expanded)
    if len(expanded) % 512:
        fail('tar_alignment')
    pos = 0
    physical = 0
    while pos + 512 <= len(expanded):
        if time.monotonic() > deadline:
            fail('archive_validation_timeout')
        header = expanded[pos:pos+512]
        if not any(header):
            if pos + 1024 > len(expanded) or any(expanded[pos:]):
                fail('tar_trailer')
            break
        physical += 1
        if physical > cfg['max_members'] * 2 + 2:
            fail('tar_physical_header_limit')
        if header[124] & 128:
            fail('tar_base256_size')
        try:
            size = int(header[124:136].strip(b'\x00 '), 8)
        except ValueError:
            fail('tar_size_invalid')
        kind = header[156:157]
        if kind not in (b'0', b'\x00', b'x'):
            fail('tar_member_type')
        if size > cfg['max_expanded_bytes'] or pos + 512 + size > len(expanded):
            fail('tar_member_bounds')
        if kind == b'x':
            if size > 65536:
                fail('pax_size_limit')
            payload = expanded[pos+512:pos+512+size]
            cursor = 0
            keys = set()
            while cursor < len(payload):
                space = payload.find(b' ', cursor)
                if space < cursor or space - cursor > 10:
                    fail('pax_record_invalid')
                try:
                    length = int(payload[cursor:space])
                except ValueError:
                    fail('pax_record_invalid')
                end = cursor + length
                if length <= space-cursor+2 or end > len(payload) or payload[end-1:end] != b'\n':
                    fail('pax_record_invalid')
                record = payload[space+1:end-1]
                key, sep, value = record.partition(b'=')
                if sep != b'=' or key not in (b'path',) or key in keys:
                    fail('pax_key_invalid')
                safe_path(value.decode('utf-8', errors='strict'))
                keys.add(key)
                cursor = end
        pos += 512 + ((size + 511) // 512) * 512
    else:
        fail('tar_missing_trailer')
    records = {}
    with tarfile.open(fileobj=io.BytesIO(expanded), mode='r:') as archive:
        for member in archive:
            if time.monotonic() > deadline or len(records) >= cfg['max_members']:
                fail('tar_logical_budget')
            name = safe_path(member.name)
            if not member.isfile() or name in records or member.size > cfg['max_expanded_bytes']:
                fail('tar_member_invalid')
            for parent in PurePosixPath(name).parents:
                if str(parent) != '.' and str(parent) in records:
                    fail('tar_parent_collision')
            if any(other.startswith(name + '/') for other in records):
                fail('tar_parent_collision')
            stream = archive.extractfile(member)
            if stream is None:
                fail('tar_payload_missing')
            payload = stream.read(member.size + 1)
            if len(payload) != member.size:
                fail('tar_payload_size')
            records[name] = payload
    if MANIFEST not in records:
        fail('manifest_missing')
    manifest = json.loads(records.pop(MANIFEST).decode('utf-8'), object_pairs_hook=unique_object)
    if not isinstance(manifest, dict) or manifest.get('schema') != 1 or not isinstance(manifest.get('files'), dict):
        fail('manifest_schema')
    if manifest.get('image') != cfg['image'] or set(manifest['files']) != set(records):
        fail('manifest_members_or_image')
    for name, content in records.items():
        expected = manifest['files'][name]
        if not isinstance(expected, dict) or type(expected.get('bytes')) is not int or expected['bytes'] != len(content) or expected.get('sha256') != hashlib.sha256(content).hexdigest():
            fail('manifest_checksum')
    if 'db.sqlite3' not in records or 'rsa_key.pem' not in records or '.vaultwarden-volume-ready' not in records:
        fail('recovery_members_missing')
    db = sqlite3.connect(':memory:')
    try:
        db.enable_load_extension(False)
        native_database = records['db.sqlite3']
        if len(native_database) < 100 or native_database[:16] != b'SQLite format 3\x00' or native_database[18:20] not in (b'\x01\x01', b'\x02\x02'):
            fail('sqlite_header_format')
        validation_database = native_database
        if native_database[18:20] == b'\x02\x02':
            # sqlite.org/c3ref/deserialize.html: WAL cannot open in-memory.
            # Change only the validation copy, never the archived/restored bytes.
            validation_database = native_database[:18] + b'\x01\x01' + native_database[20:]
        db.deserialize(validation_database)
        db.execute('PRAGMA trusted_schema=OFF')
        db.execute('PRAGMA query_only=ON')
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            fail('restored_sqlite_integrity')
        if db.execute("SELECT type FROM sqlite_schema WHERE name='users'").fetchall() != [('table',)]:
            fail('restored_domain_table_invalid')
        users = db.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    finally:
        db.close()
    return expanded, manifest, {'payload_files': len(records), 'physical_headers': physical, 'expanded_bytes': len(expanded), 'sqlite_integrity': 'ok', 'users': users}

SNAPSHOT = r'''
import os,sys,json,stat,sqlite3,subprocess,hashlib,tarfile,io
root=ROOT
container=CONTAINER
limit=LIMIT
p=subprocess.run(['docker','ps','-a','--format','{{.Names}}'],capture_output=True,text=True)
if p.returncode != 0: raise SystemExit('writer_inventory_unobservable')
if container in p.stdout.splitlines():
 p=subprocess.run(['docker','inspect',container],capture_output=True,text=True)
 if p.returncode != 0: raise SystemExit('writer_state_unobservable')
 if json.loads(p.stdout)[0]['State']['Running']: raise SystemExit('writer_not_stopped')
if os.stat(root).st_dev == os.stat('/srv').st_dev or not os.path.isfile(root+'/.vaultwarden-volume-ready'): raise SystemExit('encrypted_mount_missing')
source=sqlite3.connect('file:'+root+'/db.sqlite3?mode=ro',uri=True)
source.enable_load_extension(False);source.execute('PRAGMA trusted_schema=OFF');source.execute('PRAGMA query_only=ON')
if source.execute('PRAGMA page_count').fetchone()[0]*source.execute('PRAGMA page_size').fetchone()[0]>limit:raise SystemExit('source_database_budget')
memory=sqlite3.connect(':memory:');source.backup(memory);source.close()
if memory.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': raise SystemExit('source_sqlite_integrity')
db=memory.serialize();memory.close()
files={'db.sqlite3':{'bytes':len(db),'sha256':hashlib.sha256(db).hexdigest()}}
paths=[];total=len(db)
for directory,dirs,names in os.walk(root,followlinks=False):
 dirs.sort();names.sort()
 for name in list(dirs):
  path=os.path.join(directory,name)
  if os.path.islink(path): raise SystemExit('source_directory_symlink')
  if directory==root and name in ['tmp','icon_cache']: dirs.remove(name)
 for name in names:
  path=os.path.join(directory,name);relative=os.path.relpath(path,root).replace(os.sep,'/')
  if directory==root and name in ['db.sqlite3','db.sqlite3-wal','db.sqlite3-shm']: continue
  if relative=='backup-manifest.json': raise SystemExit('reserved_manifest_collision')
  s=os.lstat(path)
  if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1: raise SystemExit('source_not_regular')
  h=hashlib.sha256();fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
  with os.fdopen(fd,'rb') as stream:
   before=os.fstat(stream.fileno())
   for chunk in iter(lambda:stream.read(1048576),b''):h.update(chunk)
   after=os.fstat(stream.fileno())
  if (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino): raise SystemExit('source_changed')
  total+=s.st_size
  if total>limit or len(files)>=10000: raise SystemExit('source_budget')
  files[relative]={'bytes':s.st_size,'sha256':h.hexdigest()};paths.append((relative,path,s.st_size))
manifest={'schema':1,'image':IMAGE,'files':files,'excluded_ephemeral':['tmp','icon_cache','db.sqlite3-wal','db.sqlite3-shm'],'sqlite_snapshot':'online_backup_api_after_resource_quiescence'}
with tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz',format=tarfile.PAX_FORMAT) as archive:
 def add(name,size,stream):
  item=tarfile.TarInfo(name);item.size=size;item.mode=0o600;item.uid=1000;item.gid=1000;item.mtime=0
  archive.addfile(item,stream)
 metadata=json.dumps(manifest,sort_keys=True).encode();add('backup-manifest.json',len(metadata),io.BytesIO(metadata))
 add('db.sqlite3',len(db),io.BytesIO(db))
 for relative,path,size in paths:
  fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
  with os.fdopen(fd,'rb') as stream:add(relative,size,stream)
'''

RESTORE = r'''
import os,sys,io,tarfile,json,hashlib,stat
base=BASE;target=TARGET
if os.stat(base).st_dev == os.stat('/srv').st_dev:raise SystemExit('encrypted_restore_mount_missing')
if not os.path.exists(base+'/restores'):os.mkdir(base+'/restores',0o700)
if os.path.islink(base+'/restores') or os.path.lexists(target):raise SystemExit('restore_target_not_fresh')
os.mkdir(target,0o700);os.chown(target,1000,1000)
data=sys.stdin.buffer.read(LIMIT+1)
if len(data)>LIMIT:raise SystemExit('restore_input_limit')
archive=tarfile.open(fileobj=io.BytesIO(data),mode='r:')
manifest=json.load(archive.extractfile('backup-manifest.json'))
count=0
rootfd=os.open(target,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
try:
 for member in archive:
  if member.name=='backup-manifest.json':continue
  parts=member.name.split('/')
  if not member.isfile() or any(p in ['','.','..'] for p in parts) or member.name.startswith('/') or member.name not in manifest['files']:raise SystemExit('restore_member_invalid')
  parent=os.dup(rootfd)
  try:
   for part in parts[:-1]:
    try:os.mkdir(part,0o700,dir_fd=parent);os.chown(part,1000,1000,dir_fd=parent,follow_symlinks=False)
    except FileExistsError:pass
    nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent);os.close(parent);parent=nxt
   fd=os.open(parts[-1],os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent)
   stream=archive.extractfile(member);h=hashlib.sha256();written=0
   try:
    while True:
     chunk=stream.read(1048576)
     if not chunk:break
     offset=0
     while offset<len(chunk):offset+=os.write(fd,chunk[offset:])
     h.update(chunk);written+=len(chunk)
    os.fchown(fd,1000,1000);os.fsync(fd)
   finally:os.close(fd)
   expected=manifest['files'][member.name]
   if h.hexdigest()!=expected['sha256'] or written!=expected['bytes']:raise SystemExit('restore_checksum')
   count+=1
  finally:os.close(parent)
finally:os.close(rootfd);archive.close()
print(json.dumps({'restored_files':count,'checksums_match':True,'encrypted_target':True}))
'''

class Operator:
    def __init__(self, cfg):
        self.cfg = cfg
        self.root = Path(cfg['state_root'])
        self.token = None
        self.phase = 'initial'

    def command(self, args, data=None, timeout=120):
        try:
            p = subprocess.run(args, input=data, capture_output=True, timeout=timeout)
        except (subprocess.TimeoutExpired, OSError):
            fail('child_timeout_or_unavailable')
        if p.returncode:
            category = {'ssh':'ssh','rclone':'rclone','proton-pass-agent':'credential_wrapper'}.get(Path(args[0]).name, 'other')
            fail('child_'+category+'_failed_at_'+self.phase)
        return p.stdout

    def field(self, title, field):
        self.command([self.cfg['proton_wrapper'], 'info'])
        env = os.environ.copy()
        env['PROTON_PASS_AGENT_REASON'] = 'Authorized exact-resource Vaultwarden backup/recovery; required named field only'
        p = subprocess.run([self.cfg['proton_wrapper'], 'item', 'view', '--vault-name', self.cfg['credential_vault_name'], '--item-title', title, '--field', field], capture_output=True, timeout=90, env=env)
        if p.returncode:
            fail('credential_field_unavailable')
        value = p.stdout.decode('utf-8').removesuffix('\n')
        if not value or '\n' in value or '\r' in value:
            fail('credential_field_encoding')
        return value

    def api(self, suffix='', method='GET', data=None):
        req = urllib.request.Request(self.cfg['coolify_url']+'/services/'+self.cfg['resource_uuid']+suffix,
            data=json.dumps(data).encode() if data is not None else None,
            headers={'Authorization': 'Bearer '+self.token, 'Content-Type': 'application/json'}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read(2000000))
        except urllib.error.HTTPError as error:
            if method == 'GET' and suffix in ('/start', '/stop') and error.code == 405:
                guard = json.loads(error.read(2000))
                if guard.get('message') == 'This endpoint has changed to a POST request.':
                    return {'post_guard_verified': True}
            fail('coolify_operation_failed_reconcile_before_retry')
        except (urllib.error.URLError, TimeoutError):
            fail('coolify_operation_failed_reconcile_before_retry')

    def remote(self, code, data=None, root=False, timeout=60):
        ast.parse(code)
        command = ('sudo -n ' if root else '')+'python3 -c '+shlex.quote(code)
        return self.command(self.cfg['ssh_argv']+[command], data=data, timeout=timeout)

    def state(self):
        code = "import subprocess,json\nn="+repr('vaultwarden-'+self.cfg['resource_uuid'])+"\np=subprocess.run(['docker','ps','-a','--format','{{.Names}}'],capture_output=True,text=True)\nif p.returncode:raise SystemExit('docker_inventory_unobservable')\nif n not in p.stdout.splitlines():print(json.dumps({'running':False,'health':None,'image':None,'present':False}))\nelse:\n p=subprocess.run(['docker','inspect',n],capture_output=True,text=True)\n if p.returncode:\n  retry=subprocess.run(['docker','ps','-a','--format','{{.Names}}'],capture_output=True,text=True)\n  if retry.returncode:raise SystemExit('docker_inventory_unobservable')\n  if n in retry.stdout.splitlines():raise SystemExit('exact_container_unobservable')\n  print(json.dumps({'running':False,'health':None,'image':None,'present':False}))\n else:\n  d=json.loads(p.stdout)[0];print(json.dumps({'running':d['State']['Running'],'health':(d['State'].get('Health') or {}).get('Status'),'image':d['Config']['Image'],'present':True}))\n"
        return json.loads(self.remote(code))

    def wait(self, running, timeout=90):
        end = time.monotonic()+timeout
        while time.monotonic() < end:
            state = self.state()
            if state.get('present', True) and state.get('image') != self.cfg['image']:
                fail('resource_image_changed')
            if state['running'] is running and (not running or state.get('health') == 'healthy'):
                return state
            time.sleep(2)
        fail('resource_state_timeout')

    def check(self):
        self.phase = 'preflight'
        self.token = self.field(self.cfg['coolify_item'], 'API Key')
        resource = self.api()
        if resource.get('name') != self.cfg['resource_name']:
            fail('exact_resource_identity')
        if len(resource.get('applications', [])) != 1 or resource['applications'][0].get('name') != 'vaultwarden' or resource.get('databases'):
            fail('resource_scope_contains_unapproved_subservices')
        for endpoint in ('/start', '/stop'):
            if self.api(endpoint) != {'post_guard_verified': True}:
                fail('native_lifecycle_surface_unverified')
        state = self.state()
        if not state.get('running') or state.get('health') != 'healthy' or state.get('image') != self.cfg['image']:
            fail('exact_live_image_or_health')
        code = "import os,socket,json\nroot="+repr(self.cfg['data_path'])+"\nprint(json.dumps({'host':socket.gethostname(),'encrypted_mount':os.stat(root).st_dev!=os.stat('/srv').st_dev,'marker':os.path.isfile(root+'/.vaultwarden-volume-ready')}))\n"
        storage = json.loads(self.remote(code))
        if storage != {'host':self.cfg['expected_host'],'encrypted_mount':True,'marker':True}:
            fail('encrypted_storage_identity')
        if shutil.disk_usage(self.root).free < self.cfg['max_archive_bytes']*3:
            fail('local_backup_capacity')
        quota = json.loads(self.command([self.cfg['rclone_bin'],'about',self.cfg['backup_remote'].split(':',1)[0]+':','--json']))
        if quota.get('free',0) < self.cfg['max_archive_bytes']*2:
            fail('drive_backup_capacity')
        return {'exact_resource':True,'healthy':True,'encrypted_storage':True,'agent_access_assessed':False}

    def read_bounded(self, args, limit, timeout):
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        reader = selectors.DefaultSelector()
        output = bytearray()
        deadline = time.monotonic() + timeout
        try:
            for pipe in (process.stdout, process.stderr):
                os.set_blocking(pipe.fileno(), False)
                reader.register(pipe, selectors.EVENT_READ)
            while reader.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    fail('bounded_reader_timeout')
                for key, _ in reader.select(min(1, remaining)):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        reader.unregister(key.fileobj)
                        continue
                    if key.fileobj is process.stdout:
                        if len(output) + len(chunk) > limit:
                            fail('bounded_reader_byte_limit')
                        output.extend(chunk)
            if process.wait(timeout=max(0.1, deadline-time.monotonic())):
                fail('bounded_reader_child_failed')
            return bytes(output)
        finally:
            reader.close()
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)

    def encrypt_snapshot(self, producer_args, artifact, timeout=120):
        producer = subprocess.Popen(producer_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        consumer = None
        try:
            consumer = subprocess.Popen([self.cfg['age_bin'],'--encrypt','--recipient',self.cfg['age_recipient'],'--output',str(artifact)],stdin=producer.stdout,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            producer.stdout.close()
            try:
                consumer.communicate(timeout=timeout)
                producer.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                fail('snapshot_encrypt_timeout')
            if producer.returncode or consumer.returncode or not artifact.is_file():
                fail('snapshot_encrypt_failed')
        finally:
            for child in (producer, consumer):
                if child is not None:
                    if child.poll() is None:
                        child.kill()
                    child.communicate(timeout=10)

    def save(self, name, report):
        target = self.root/name
        temp = self.root/(name+'.new')
        fd = os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as stream:
                json.dump(report,stream,sort_keys=True,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
            os.replace(temp,target)
        finally:
            if temp.exists(): temp.unlink()

    def backup(self):
        self.check()
        timestamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        directory = self.root/'encrypted-backups'
        directory.mkdir(mode=0o700,exist_ok=True)
        artifact = directory/('vaultwarden-'+timestamp+'.tar.gz.age')
        stopped = False
        stop_requested = False
        try:
            stop_requested = True
            self.phase = 'quiescence'
            self.api('/stop','POST',{})
            self.wait(False)
            if self.api().get('status') != 'exited':
                fail('native_stop_readback_not_exited')
            stopped = True
            self.phase = 'snapshot'
            code = SNAPSHOT.replace('ROOT',repr(self.cfg['data_path'])).replace('CONTAINER',repr('vaultwarden-'+self.cfg['resource_uuid'])).replace('LIMIT',str(self.cfg['max_expanded_bytes'])).replace('IMAGE',repr(self.cfg['image']))
            ast.parse(code)
            self.encrypt_snapshot(self.cfg['ssh_argv']+['python3 -c '+shlex.quote(code)], artifact)
            if artifact.stat().st_size > self.cfg['max_archive_bytes']:
                fail('encrypted_archive_limit')
        finally:
            if stop_requested:
                old_handlers = {s: signal.signal(s, signal.SIG_IGN) for s in (signal.SIGINT, signal.SIGTERM)} if threading.current_thread() is threading.main_thread() else {}
                try:
                    self.phase = 'recovery'
                    if not stopped:
                        self.wait(False)
                    current = self.state()
                    if current['running']:
                        fail('writer_resumed_before_snapshot_release')
                    self.api('/start','POST',{})
                    self.wait(True)
                finally:
                    for s, handler in old_handlers.items():signal.signal(s, handler)
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        remote = self.cfg['backup_remote']+'/'+artifact.name
        self.phase = 'upload'
        self.command([self.cfg['rclone_bin'],'copyto',str(artifact),remote,'--checksum','--immutable','--retries','1','--low-level-retries','2'],timeout=180)
        downloaded = self.read_bounded([self.cfg['rclone_bin'],'cat',remote],self.cfg['max_archive_bytes'],180)
        if len(downloaded) != artifact.stat().st_size or hashlib.sha256(downloaded).hexdigest() != digest:
            fail('cloud_full_byte_readback_mismatch')
        report = {'schema':1,'status':'verified','timestamp':timestamp,'artifact':str(artifact),'remote':remote,'sha256':digest,'encrypted_bytes':artifact.stat().st_size,'remote_full_byte_readback':True,'consistent_snapshot':True,'application_recovered_healthy':True,'pruned':False}
        self.save('last-backup.json',report)
        return report

    def restore(self):
        self.check()
        self.phase = 'restore_download'
        backup = json.loads((self.root/'last-backup.json').read_text(),object_pairs_hook=unique_object)
        if backup.get('status') != 'verified' or not backup['remote'].startswith(self.cfg['backup_remote']+'/'):
            fail('verified_backup_identity')
        ciphertext = self.read_bounded([self.cfg['rclone_bin'],'cat',backup['remote']],self.cfg['max_archive_bytes'],180)
        if len(ciphertext) > self.cfg['max_archive_bytes'] or hashlib.sha256(ciphertext).hexdigest() != backup['sha256']:
            fail('restore_remote_checksum')
        identity = self.field(self.cfg['age_recovery_item'],'password')
        readfd,writefd = os.pipe()
        os.write(writefd,(identity+'\n').encode());os.close(writefd)
        child = None
        try:
            child = subprocess.Popen([self.cfg['age_bin'],'--decrypt','--identity','/dev/fd/'+str(readfd)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,pass_fds=(readfd,))
            compressed,_ = child.communicate(input=ciphertext,timeout=90)
            if child.returncode: fail('backup_authentication_decryption')
        finally:
            if child is not None:
                if child.poll() is None:child.kill()
                child.communicate(timeout=10)
            os.close(readfd)
        self.phase = 'restore_validation'
        expanded,manifest,evidence = validate_archive(compressed,self.cfg)
        suffix = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S')
        target = self.cfg['restore_parent']+'/drill-'+suffix
        code = RESTORE.replace('BASE',repr(self.cfg['mount_path'])).replace('TARGET',repr(target)).replace('LIMIT',str(self.cfg['max_expanded_bytes']))
        self.phase = 'restore_write'
        restoration = json.loads(self.remote(code,data=expanded,root=True,timeout=90))
        if restoration.get('restored_files') != evidence['payload_files'] or not restoration.get('checksums_match'):
            fail('isolated_restore_write_readback')
        fixture = 'vaultwarden-restore-'+suffix.lower()
        args = ['docker','run','--detach','--name',fixture,'--label','org.example.vaultwarden-drill='+suffix,'--network','none','--user','1000:1000','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--memory','512m','--cpus','1','--pids-limit','128','--ulimit','core=0','--mount','type=bind,src='+target+',dst=/data','--tmpfs','/tmp:rw,noexec,nosuid,size=64m,mode=1777','--env','ENV_FILE=/dev/null','--env','DOMAIN='+self.cfg['restore_domain'],'--env','ROCKET_PORT=8080','--env','SIGNUPS_ALLOWED=false','--env','INVITATIONS_ALLOWED=false','--env','LOG_LEVEL=warn','--env','EXTENDED_LOGGING=false','--entrypoint','/bin/sh',self.cfg['image'],'-ec','test -f /data/.vaultwarden-volume-ready && exec /start.sh']
        self.phase = 'restore_boot'
        self.remote('import subprocess\np=subprocess.run('+repr(args)+',capture_output=True)\nraise SystemExit(p.returncode)\n')
        try:
            inspection = "import subprocess,json\np=subprocess.run(['docker','inspect',"+repr(fixture)+"],capture_output=True,text=True)\nif p.returncode:raise SystemExit('fixture_unobservable')\nd=json.loads(p.stdout)[0]\nprint(json.dumps({'image':d['Config']['Image'],'user':d['Config']['User'],'network':d['HostConfig']['NetworkMode'],'readonly':d['HostConfig']['ReadonlyRootfs'],'privileged':d['HostConfig']['Privileged'],'ports':d['HostConfig'].get('PortBindings') or {},'cap_drop':d['HostConfig'].get('CapDrop'),'security_opt':d['HostConfig'].get('SecurityOpt'),'owner':d['Config']['Labels'].get('org.example.vaultwarden-drill'),'data_sources':[m['Source'] for m in d['Mounts'] if m['Destination']=='/data']}))\n"
            observed = json.loads(self.remote(inspection))
            if observed['image'] != self.cfg['image'] or observed['user'] != '1000:1000' or observed['network'] != 'none' or not observed['readonly'] or observed['privileged'] or observed['ports'] or 'ALL' not in (observed['cap_drop'] or []) or not any(x.startswith('no-new-privileges') for x in (observed['security_opt'] or [])) or observed['owner'] != suffix or observed['data_sources'] != [target]:
                fail('restore_fixture_isolation_readback')
            end = time.monotonic()+60
            while time.monotonic()<end:
                check = "import subprocess,json\np=subprocess.run(['docker','exec',"+repr(fixture)+",'/healthcheck.sh'],capture_output=True)\nprint(json.dumps({'healthcheck_exit':p.returncode}))\n"
                if json.loads(self.remote(check))['healthcheck_exit']==0:
                    break
                time.sleep(2)
            else: fail('restored_application_health')
            dbcheck = "import sqlite3,json,hashlib\np="+repr(target)+"\nc=sqlite3.connect('file:'+p+'/db.sqlite3?mode=ro',uri=True);c.execute('PRAGMA query_only=ON');c.execute('PRAGMA trusted_schema=OFF')\nprint(json.dumps({'integrity':c.execute('PRAGMA integrity_check').fetchone()[0],'users':c.execute('SELECT COUNT(*) FROM users').fetchone()[0],'fixture_hash':hashlib.sha256(open(p+'/.vaultwarden-persistence-probe','rb').read()).hexdigest()}));c.close()\n"
            self.phase = 'restore_readonly_database_probe'
            final = json.loads(self.remote(dbcheck, root=True))
            if final['integrity'] != 'ok' or final['users'] != evidence['users'] or final['fixture_hash'] != manifest['files']['.vaultwarden-persistence-probe']['sha256']:
                fail('restored_application_data')
        finally:
            cleanup = "import subprocess,json\nn="+repr(fixture)+"\np=subprocess.run(['docker','inspect',n],capture_output=True,text=True)\nif p.returncode==0:\n d=json.loads(p.stdout)[0]\n if d['Config']['Labels'].get('org.example.vaultwarden-drill')!="+repr(suffix)+":raise SystemExit('fixture_owner_mismatch')\n q=subprocess.run(['docker','rm','--force',n],capture_output=True)\n if q.returncode:raise SystemExit(1)\nq=subprocess.run(['docker','ps','-a','--format','{{.Names}}'],capture_output=True,text=True)\nif q.returncode:raise SystemExit('cleanup_inventory_unobservable')\nprint(json.dumps({'owned_fixture_absent':n not in q.stdout.splitlines()}))\n"
            clean = json.loads(self.remote(cleanup))
            if not clean['owned_fixture_absent']: fail('restore_fixture_cleanup')
        self.wait(True)
        report = {'status':'verified','snapshot_sha256':backup['sha256'],'remote_downloaded_again':True,'authenticated_decryption':True,'complete_gzip_crc_and_tar_validation':True,'manifest_exact_members_and_hashes':True,'source_not_used_for_restore':True,'isolated_encrypted_target':target,'restored_application_healthy':True,'network':'none','published_ports':False,'fixture_removed_verified':True,'plaintext_local_files':False,'native_human_client_acceptance':False,**evidence}
        self.save('last-restore.json',report)
        return report

def main():
    os.umask(0o077)
    def cancel(_signum, _frame):
        raise KeyboardInterrupt('owned_operation_cancelled')
    for s in (signal.SIGINT, signal.SIGTERM):signal.signal(s, cancel)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('action', choices=['check','backup','restore'], nargs='?', default='check')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.action != 'check' and not args.apply:
        fail('explicit_apply_required')
    fd = os.open(args.config, os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
            fail('private_config_permissions')
        body = stream.read(65537)
        if len(body) > 65536:
            fail('private_config_limit')
    cfg = json.loads(body, object_pairs_hook=unique_object)
    if not isinstance(cfg,dict) or type(cfg.get('schema')) is not int or cfg['schema'] != 1 or cfg.get('no_prune') is not True:
        fail('private_config_contract')
    root = Path(cfg['state_root'])
    metadata = root.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
        fail('private_state_permissions')
    op = Operator(cfg)
    lock = os.open(op.root/'.backup-run.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: fail('backup_already_running')
        action = args.action
        result = op.check() if action=='check' else op.backup() if action=='backup' else op.restore()
        print(json.dumps({'operation':action,'status':'verified','encrypted_bytes':result.get('encrypted_bytes'),'restored_payload_files':result.get('payload_files'),'human_client_acceptance':False},sort_keys=True))
    finally:
        os.close(lock)

if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        gate = str(error) if isinstance(error,GateError) else type(error).__name__
        print(json.dumps({'status':'failed','gate':gate,'no_automatic_retry':True},sort_keys=True))
        sys.exit(1)
