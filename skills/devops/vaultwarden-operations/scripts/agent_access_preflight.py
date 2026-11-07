#!/usr/bin/env python3
"""Metadata-only candidate preflight; never grants, unlocks, syncs or reads items."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import time
from urllib.parse import urlsplit

MAX_BYTES = 65536


class GateError(Exception):
    """Only fixed internal gate codes may cross the output boundary."""


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise GateError('duplicate_json_key')
        result[key] = value
    return result


def parse_json(body):
    if len(body) > MAX_BYTES:
        raise GateError('input_byte_limit')
    try:
        return json.loads(body, object_pairs_hook=unique_object)
    except (UnicodeError, ValueError):
        raise GateError('invalid_json') from None


def validate_policy(policy):
    required = {'schema', 'enabled', 'account_kind', 'server_origin', 'account_id',
                'cli_state_directory', 'expires_at', 'scopes'}
    if not isinstance(policy, dict) or set(policy) != required:
        raise GateError('policy_shape')
    if type(policy['schema']) is not int or policy['schema'] != 1:
        raise GateError('policy_schema')
    if type(policy['enabled']) is not bool or policy['account_kind'] != 'dedicated':
        raise GateError('dedicated_account_required')
    for key in ('server_origin', 'account_id', 'cli_state_directory', 'expires_at'):
        if not isinstance(policy[key], str) or not policy[key] or len(policy[key]) > 2048:
            raise GateError('policy_scalar')
    origin = urlsplit(policy['server_origin'])
    try:
        port = origin.port
    except ValueError:
        raise GateError('origin_invalid') from None
    if (origin.scheme != 'https' or not origin.hostname or origin.username or origin.password
            or origin.path or origin.query or origin.fragment or port not in (None, 443)):
        raise GateError('origin_invalid')
    if not Path(policy['cli_state_directory']).is_absolute():
        raise GateError('isolated_state_path_required')
    try:
        expiry = dt.datetime.fromisoformat(policy['expires_at'].replace('Z', '+00:00'))
        if expiry.tzinfo is None or expiry.utcoffset() != dt.timedelta(0):
            raise ValueError()
    except ValueError:
        raise GateError('expiry_invalid') from None
    scopes = policy['scopes']
    if not isinstance(scopes, list) or not 1 <= len(scopes) <= 32:
        raise GateError('scope_limit')
    seen = set()
    for scope in scopes:
        if not isinstance(scope, dict) or set(scope) != {'profile', 'item_id', 'consumer', 'operation'}:
            raise GateError('scope_shape')
        if any(not isinstance(v, str) or not v or len(v) > 256 for v in scope.values()):
            raise GateError('scope_scalar')
        # IDs are preserved literally: no repair, title search or normalization.
        if not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', scope['item_id']):
            raise GateError('item_id_invalid')
        if scope['operation'] != 'authenticated_read' or scope['consumer'] != 'fixed_https_api':
            raise GateError('pilot_readonly_consumer_required')
        identity = tuple(scope[k] for k in ('profile', 'item_id', 'consumer', 'operation'))
        if '*' in scope.values() or identity in seen:
            raise GateError('wildcard_or_duplicate_scope')
        seen.add(identity)
    return expiry


def read_policy(path, protected=False):
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise GateError('policy_not_regular')
            if protected and (info.st_uid != os.getuid() or info.st_mode & 0o077):
                raise GateError('private_policy_permissions')
            return parse_json(stream.read(MAX_BYTES + 1))
    except OSError:
        raise GateError('policy_unavailable') from None


def validate_state_path(path):
    candidate = Path(path)
    try:
        # Reject symlink ancestors too; do not borrow the default CLI app-data store.
        if any(p.is_symlink() for p in (candidate, *candidate.parents)):
            raise GateError('state_symlink')
        info = candidate.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise GateError('private_state_permissions')
        forbidden = [Path.home() / '.config/Bitwarden CLI',
                     Path.home() / 'Library/Application Support/Bitwarden CLI']
        if candidate.resolve() in [p.resolve() for p in forbidden]:
            raise GateError('human_or_default_state_forbidden')
    except OSError:
        raise GateError('private_state_unavailable') from None


def bounded_status(binary, state_directory, timeout=20):
    # No inherited session, password, API key, proxy or task environment.
    env = {k: os.environ[k] for k in ('HOME', 'PATH', 'TMPDIR', 'LANG') if k in os.environ}
    env.update({'BITWARDENCLI_APPDATA_DIR': state_directory, 'NO_COLOR': '1'})
    process = subprocess.Popen([binary, 'status', '--nointeraction'], env=env,
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    selector = selectors.DefaultSelector()
    captured = bytearray()
    total = 0
    deadline = time.monotonic() + timeout
    try:
        for pipe in (process.stdout, process.stderr):
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GateError('status_timeout')
            for key, _ in selector.select(min(remaining, 0.1)):
                chunk = os.read(key.fileobj.fileno(), 8192)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                total += len(chunk)
                if total > MAX_BYTES:
                    raise GateError('status_byte_limit')
                if key.fileobj is process.stdout:
                    captured.extend(chunk)
        try:
            code = process.wait(timeout=max(0.01, deadline-time.monotonic()))
        except subprocess.TimeoutExpired:
            raise GateError('status_timeout') from None
        if code:
            raise GateError('status_failed')
        result = parse_json(bytes(captured))
        if not isinstance(result, dict) or result.get('status') not in ('locked', 'unlocked', 'unauthenticated'):
            raise GateError('status_shape')
        return result
    finally:
        selector.close()
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
        for pipe in (process.stdout, process.stderr):
            pipe.close()


def inspect_policy(policy, now=None, cli_status=None):
    expiry = validate_policy(policy)
    now = now or dt.datetime.now(dt.timezone.utc)
    gates = []
    if not policy['enabled']:
        gates.append('policy_disabled')
    if expiry <= now:
        gates.append('policy_expired')
    report = {'policy_valid': True, 'cli_probed': cli_status is not None,
              'server_matches': False, 'account_matches': False, 'parent_locked': False,
              'caller_authenticated': False, 'destination_permissions_verified': False,
              'secret_executor_implemented': False, 'agent_access_enabled': False}
    if cli_status is None:
        gates.append('cli_not_probed')
    else:
        report['server_matches'] = cli_status.get('serverUrl') == policy['server_origin']
        report['account_matches'] = cli_status.get('userId') == policy['account_id']
        report['parent_locked'] = cli_status.get('status') == 'locked'
        for flag, code in [('server_matches', 'server_mismatch'), ('account_matches', 'account_mismatch'),
                           ('parent_locked', 'parent_not_locked')]:
            if not report[flag]:
                gates.append(code)
    # Policy/profile names are not authenticated callers and never issue a grant.
    gates.extend(['caller_authentication_pending', 'destination_permissions_pending',
                  'private_executor_pending'])
    return {'status': 'blocked', **report, 'blocking_codes': gates}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy', required=True)
    parser.add_argument('--probe-cli', action='store_true', help='status only in the exact dedicated state')
    args = parser.parse_args()
    try:
        policy = read_policy(args.policy, protected=args.probe_cli)
        validate_policy(policy)
        status = None
        if args.probe_cli:
            validate_state_path(policy['cli_state_directory'])
            binary = shutil.which('bw')
            if not binary:
                raise GateError('cli_unavailable')
            status = bounded_status(binary, policy['cli_state_directory'])
        report = inspect_policy(policy, cli_status=status)
        print(json.dumps(report, sort_keys=True))
        return 2  # Never ready for secret use; no operational executor ships here.
    except BaseException as error:
        code = str(error) if isinstance(error, GateError) else 'preflight_failed'
        print(json.dumps({'status': 'blocked', 'agent_access_enabled': False, 'blocking_codes': [code]}))
        return 2


if __name__ == '__main__':
    sys.exit(main())
