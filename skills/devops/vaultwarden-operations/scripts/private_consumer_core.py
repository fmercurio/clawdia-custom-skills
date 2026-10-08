#!/usr/bin/env python3
"""Source-only private-consumer core; no CLI, vault connector, enrollment or daemon.

Only a trusted host may construct Authority/Executor/provider/consumer objects.
Grant and caller proofs travel in memory over a separately reviewed private
transport, NOT model-visible tool arguments. Real Bitwarden custody and OS
isolation are intentionally absent; default execution is disabled.
"""
import dataclasses
import hashlib
import hmac
import http.client
import json
import math
import os
from pathlib import Path
import re
import secrets
import ssl
import stat
import threading
import time
from urllib.parse import urlsplit

UUID = re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}')
CODES = frozenset({'authorization_denied', 'executor_disabled', 'parent_not_locked',
                   'private_provider_failed', 'visibility_or_permission_denied',
                   'external_outcome_unknown', 'cleanup_unverified', 'executor_busy'})


class Denied(Exception):
    def __init__(self, code='authorization_denied'):
        # Never let an injected provider/transport replay an exception payload.
        super().__init__(code if code in CODES else 'authorization_denied')


@dataclasses.dataclass(frozen=True)
class Scope:
    caller: str
    profile: str
    item_id: str
    collection_id: str
    operation: str
    target_sha256: str

    def validate(self):
        for value in dataclasses.asdict(self).values():
            if not isinstance(value, str) or not value or len(value)>128 or '*' in value:
                raise Denied()
        for value in [self.item_id, self.collection_id]:
            if not UUID.fullmatch(value):raise Denied()
        if not re.fullmatch('[0-9a-f]{64}',self.target_sha256):raise Denied()


@dataclasses.dataclass(frozen=True)
class Grant:
    payload: bytes = dataclasses.field(repr=False)
    signature: bytes = dataclasses.field(repr=False)


@dataclasses.dataclass(frozen=True)
class Material:
    token: str = dataclasses.field(repr=False)
    visible_items: frozenset
    visible_collections: frozenset
    permissions_verified: object


def mac(key, domain, data):
    return hmac.new(key, domain+data, hashlib.sha256).digest()


def caller_proof(key, grant):
    """Private caller-side function; never publish keys/proofs as tool output."""
    return mac(key, b'vw-caller-v1\0', grant.payload+grant.signature)


def private_directory_fd(directory):
    """Open each ancestor without following links; retain final directory FD."""
    path = Path(directory)
    if not path.is_absolute() or '..' in path.parts:raise Denied()
    fd = os.open('/', os.O_RDONLY|os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            next_fd = os.open(part, os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd);fd = next_fd
            info = os.fstat(fd)
            if info.st_uid not in (0, os.getuid()) or info.st_mode & 0o022:
                raise Denied()
        info = os.fstat(fd)
        if info.st_uid!=os.getuid() or info.st_mode & 0o077:raise Denied()
        return fd
    except BaseException:
        os.close(fd)
        raise Denied() from None


class Authority:
    """Trusted operator issuer; single-use markers persist, keys stay in memory.

    Revoke is process-local. Restart with NEW issuer/caller keys; do not claim a
    distributed revocation service. Private installation/caller custody pending.
    """
    def __init__(self, issuer_key, callers, ledger, clock=time.time):
        if not isinstance(issuer_key, bytes) or len(issuer_key)!=32:raise Denied()
        if not isinstance(callers, dict) or not callers:raise Denied()
        if any(not isinstance(k,str) or not k or not isinstance(v,bytes) or len(v)!=32
               or hmac.compare_digest(v,issuer_key) for k,v in callers.items()):raise Denied()
        if len(set(callers.values()))!=len(callers):raise Denied()
        self._issuer = issuer_key
        self._callers = dict(callers)
        self._revoked = set()
        self._clock = clock
        self._lock = threading.RLock()
        self._fd = private_directory_fd(ledger)

    def close(self):
        with self._lock:
            if self._fd is not None:os.close(self._fd);self._fd = None
            self._issuer = None;self._callers.clear()

    def revoke(self, caller):
        with self._lock:self._revoked.add(caller)

    def is_revoked(self, caller):
        with self._lock:return caller in self._revoked

    def issue(self, scope, lifetime=30):
        with self._lock:
            scope.validate()
            if self._fd is None or scope.caller not in self._callers or scope.caller in self._revoked:
                raise Denied()
            if type(lifetime) is not int or not 1<=lifetime<=60:raise Denied()
            now = self._clock()
            if not isinstance(now,(int,float)) or not math.isfinite(now):raise Denied()
            body = {'scope':dataclasses.asdict(scope),'issued':now,'expires':now+lifetime,
                    'nonce':secrets.token_hex(32),'schema':1}
            payload = json.dumps(body,sort_keys=True,separators=(',',':')).encode()
            return Grant(payload, mac(self._issuer,b'vw-issuer-v1\0',payload))

    def validate(self, grant, proof, expected):
        with self._lock:
            try:
                expected.validate()
                if (self._fd is None or not isinstance(grant,Grant)
                        or not isinstance(grant.payload,bytes) or len(grant.payload)>4096
                        or not isinstance(grant.signature,bytes) or len(grant.signature)!=32
                        or not isinstance(proof,bytes) or len(proof)!=32):raise Denied()
                if not hmac.compare_digest(grant.signature,
                        mac(self._issuer,b'vw-issuer-v1\0',grant.payload)):raise Denied()
                body = json.loads(grant.payload)
                if set(body)!={'schema','scope','issued','expires','nonce'} or body['schema']!=1:
                    raise Denied()
                if body['scope']!=dataclasses.asdict(expected):raise Denied()
                if expected.caller in self._revoked:raise Denied()
                key = self._callers.get(expected.caller)
                if key is None or not hmac.compare_digest(proof,caller_proof(key,grant)):raise Denied()
                now = self._clock()
                if not (body['issued']<=now<body['expires'] and 0<body['expires']-body['issued']<=60):
                    raise Denied()
                if not re.fullmatch('[0-9a-f]{64}',body['nonce']):raise Denied()
                return body['nonce']
            except BaseException:
                raise Denied() from None

    def claim(self, grant, proof, expected):
        with self._lock:
            nonce = self.validate(grant,proof,expected)
            assert self._fd is not None
            # Atomic fail-closed cross-instance replay boundary, no raw capabilities.
            name = hashlib.sha256(nonce.encode()).hexdigest()
            try:
                fd = os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,
                             0o600,dir_fd=self._fd)
                try:os.fsync(fd)
                finally:os.close(fd)
                os.fsync(self._fd)
            except OSError:raise Denied() from None


class FixedHTTPSRead:
    """One configured GET, verified TLS, no redirects/proxy environment/retry.

    Returns no body/header/token. Expected SHA-256 is trusted synthetic readback,
    not a general-purpose data export. Process/DNS hard-deadline supervision is
    not implemented here; a production worker must supply that outer boundary.
    """
    def __init__(self, url, expected_sha256, context=None, timeout=5):
        try:
            parsed = urlsplit(url)
            port = parsed.port or 443
            if (parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password
                    or parsed.query or parsed.fragment or not parsed.path.startswith('/')
                    or '\\' in url or '%' in parsed.path or '..' in parsed.path.split('/')
                    or any(ord(c)<33 or ord(c)>126 for c in url)):
                raise Denied()
            if not re.fullmatch('[0-9a-f]{64}',expected_sha256):raise Denied()
            if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=10:
                raise Denied()
            context = context or ssl.create_default_context()
            if context.verify_mode!=ssl.CERT_REQUIRED or not context.check_hostname:raise Denied()
            self._host,self._port,self._path = parsed.hostname,port,parsed.path
            self._digest,self._context,self._timeout = expected_sha256,context,timeout
            binding = json.dumps(['GET',self._host,self._port,self._path,self._digest],
                                 separators=(',',':')).encode()
            self.target_sha256 = hashlib.sha256(binding).hexdigest()
        except BaseException:raise Denied() from None

    def __call__(self, token):
        if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9._~-]{1,4096}',token):
            raise Denied('visibility_or_permission_denied')
        connection = http.client.HTTPSConnection(self._host,self._port,
                            context=self._context,timeout=self._timeout)
        try:
            deadline = time.monotonic()+self._timeout
            connection.request('GET',self._path,headers={'Authorization':'Bearer '+token,
                                 'Accept':'application/json','Connection':'close'})
            response = connection.getresponse()
            if response.status!=200:raise Denied('external_outcome_unknown')
            body = bytearray()
            while True:
                remaining = deadline-time.monotonic()
                if remaining<=0:raise Denied('external_outcome_unknown')
                if connection.sock is not None:connection.sock.settimeout(remaining)
                chunk = response.read(min(8192,65537-len(body)))
                body.extend(chunk)
                if len(body)>65536:raise Denied('external_outcome_unknown')
                if not chunk:break
            if not hmac.compare_digest(hashlib.sha256(body).hexdigest(),self._digest):
                raise Denied('external_outcome_unknown')
        except BaseException:
            raise Denied('external_outcome_unknown') from None
        finally:connection.close()


class Executor:
    """Private trusted-host composition. NOT an exposed Hermes tool/MCP service.

    Provider must supply parent_locked() and context-managed open_exact(). Its
    real CLI session isolation, visibility proof and cleanup need separate review.
    No trusted synthetic provider implementation ships as a production adapter.
    """
    def __init__(self, authority, scope, provider, consumer, enabled=False):
        self.authority,self.scope,self.provider,self.consumer = authority,scope,provider,consumer
        self.enabled = enabled is True
        self._busy = threading.Lock()

    def execute(self, grant, proof):
        attempted = False
        code = 'executor_disabled'
        locked = False
        if not self.enabled:
            return {'status':'blocked','code':code,'parent_locked':False,'external_attempted':False}
        if not self._busy.acquire(blocking=False):
            return {'status':'blocked','code':'executor_busy','parent_locked':False,'external_attempted':False}
        authorized = False
        try:
            # Authentication before any provider status/read/unlock or external request.
            self.authority.claim(grant,proof,self.scope)
            authorized = True
            if getattr(self.consumer,'target_sha256',None)!=self.scope.target_sha256:
                raise Denied()
            code = 'parent_not_locked'
            locked = self.provider.parent_locked() is True
            if not locked:raise Denied('parent_not_locked')
            code = 'private_provider_failed'
            with self.provider.open_exact(self.scope.item_id,self.scope.collection_id) as material:
                if (not isinstance(material,Material) or material.permissions_verified is not True
                        or not isinstance(material.token,str)
                        or not re.fullmatch(r'[A-Za-z0-9._~-]{1,4096}',material.token)
                        or material.visible_items!=frozenset({self.scope.item_id})
                        or material.visible_collections!=frozenset({self.scope.collection_id})):
                    raise Denied('visibility_or_permission_denied')
                # Re-check expiry/revocation after private unlock, just before dispatch.
                self.authority.validate(grant,proof,self.scope)
                attempted = True
                code = 'external_outcome_unknown'
                self.consumer(material.token)
                code = 'cleanup_unverified'
            # Only successful context-manager teardown may promote acceptance.
            code = 'private_read_verified'
            material = None
        except Denied as error:
            code = str(error)
        except BaseException:
            # Fixed code already records the last known phase; never replay errors.
            pass
        finally:
            if authorized:
                try:locked = self.provider.parent_locked() is True
                except BaseException:locked = False
                if not locked and code!='parent_not_locked':code = 'cleanup_unverified'
            self._busy.release()
        return {'status':'verified' if code=='private_read_verified' else 'blocked',
                'code':code,'parent_locked':locked,'external_attempted':attempted}
