#!/usr/bin/env python3
"""Generic Agilize Keycloak/OIDC PKCE login script.

Supports multiple credential sources: KeePassXC, environment variables, or config file.
Never prints passwords, TOTP codes, cookies, or tokens.

Usage:
    # Using env vars (AGILIZE_USERNAME, AGILIZE_PASSWORD, AGILIZE_TOTP_SECRET):
    python agilize_login.py --verify --company-id "<uuid>" --company-cnpj "<cnpj>"

    # Using KeePassXC:
    python agilize_login.py --verify \
      --db /path/to/db.kdbx --key-file /path/to.keyx --entry /Agilize \
      --company-id "<uuid>" --company-cnpj "<cnpj>"

    # Using config file (~/.config/agilize.json):
    python agilize_login.py --verify --config ~/.config/agilize.json

    # Authenticated GET:
    python agilize_login.py \
      --api-get "/api/v1/companies/<uuid>/finance-accounts" \
      --output /tmp/agilize-accounts.json \
      --company-id "<uuid>" --company-cnpj "<cnpj>"

Config file format (~/.config/agilize.json):
    {
      "username": "user@example.com",
      "password": "*** NOTE: file should be chmod 600 ***",
      "totp_secret": "BASE32SEED",
      "company_id": "uuid-here",
      "company_cnpj": "00000000000000"
    }
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import stat
import struct
import subprocess
import sys
import time
import urllib.parse
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import requests
except Exception as exc:
    print(f"ERROR: missing requests: {exc}", file=sys.stderr)
    sys.exit(2)

# Agilize constants (same for all tenants)
AUTH_URL = "https://sso.agilize.com.br/auth/realms/AgilizeAPPs/protocol/openid-connect/auth"
TOKEN_URL = "https://sso.agilize.com.br/auth/realms/AgilizeAPPs/protocol/openid-connect/token"
API_BASE = "https://app.agilize.com.br"
DEFAULT_CLIENT_ID = "agilize-legacy-client"
DEFAULT_REDIRECT_URI = "https://app.agilize.com.br/"
API_PATH_PREFIX = "/api"
EXPECTED_SSO_SCHEME = urllib.parse.urlsplit(AUTH_URL).scheme
EXPECTED_SSO_HOST = urllib.parse.urlsplit(AUTH_URL).netloc


class FormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.forms: List[dict] = []
        self._current: Optional[dict] = None

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attrs_d = {k.lower(): (v or "") for k, v in attrs}
        if tag.lower() == "form":
            self._current = {"action": attrs_d.get("action", ""), "method": attrs_d.get("method", "get"), "fields": []}
            self.forms.append(self._current)
        elif self._current is not None and tag.lower() in {"input", "button"}:
            self._current["fields"].append(attrs_d)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "form":
            self._current = None


def die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


# ─── Credential loading ──────────────────────────────────────────────

def load_config_file(path: str) -> dict:
    p = Path(path).expanduser()
    if not p.exists():
        die(f"config file not found: {p}")
    mode = stat.S_IMODE(p.stat().st_mode)
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        die(f"config file permissions are too broad: {p}; run chmod 600")
    try:
        return json.loads(p.read_text())
    except Exception as exc:
        die(f"invalid config file: {exc}")


def load_env_creds() -> dict:
    username = os.environ.get("AGILIZE_USERNAME", "")
    password = os.environ.get("AGILIZE_PASSWORD", "")
    totp = os.environ.get("AGILIZE_TOTP", "")
    totp_secret = os.environ.get("AGILIZE_TOTP_SECRET", "")
    company_id = os.environ.get("AGILIZE_COMPANY_ID", "")
    company_cnpj = os.environ.get("AGILIZE_COMPANY_CNPJ", "")
    if not username and not password:
        return {}
    return {
        "username": username,
        "password": password,
        "totp": totp,
        "totp_secret": totp_secret,
        "company_id": company_id,
        "company_cnpj": company_cnpj,
    }


def load_keepass(db: str, key_file: str, entry: str) -> dict:
    def kp_run(args: List[str]) -> str:
        cmd = ["keepassxc-cli"] + args + ["--no-password", "-k", key_file, db, entry]
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=20)
        if proc.returncode != 0:
            die(f"keepassxc-cli failed for entry {entry!r} (exit {proc.returncode})")
        return proc.stdout.strip()

    username = kp_run(["show", "-a", "UserName"]).strip()
    password = kp_run(["show", "-a", "Password", "--show-protected"]).strip()

    # TOTP
    totp = ""
    totp_seed = ""
    totp_raw = kp_run(["show", "-t"]).strip()
    if re.fullmatch(r"\d{6,8}", totp_raw):
        totp = totp_raw
    else:
        # Try to read TOTP seed (otp attribute)
        try:
            seed_raw = kp_run(["show", "-a", "otp"]).strip()
            if seed_raw:
                totp_seed = seed_raw
        except Exception:
            pass

    if not username:
        die("KeePass username is empty")
    if not password:
        die("KeePass password is empty")

    return {"username": username, "password": password, "totp": totp, "totp_seed": totp_seed}


def generate_totp(secret: str) -> str:
    """Generate a TOTP code from a base32 secret."""
    key = base64.b32decode(secret.replace(" ", "").upper() + "=" * (-len(secret) % 8))
    counter = int(time.time()) // 30
    msg = struct.pack(">Q", counter)
    h = hmac.new(key, msg, hashlib.sha1).digest()
    offset = h[-1] & 0x0F
    code = struct.unpack(">I", h[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{code % 1000000:06d}"


def resolve_credentials(args: argparse.Namespace) -> dict:
    """Resolve credentials from the highest-priority source."""
    # Priority: --config file > KeePassXC > environment variables
    if args.config:
        cfg = load_config_file(args.config)
        if "totp_secret" in cfg and not cfg.get("totp"):
            cfg["totp"] = generate_totp(cfg["totp_secret"])
        return cfg

    if args.db and args.key_file and args.entry:
        creds = load_keepass(args.db, args.key_file, args.entry)
        # Override with explicit args if given
        if args.company_id:
            creds["company_id"] = args.company_id
        if args.company_cnpj:
            creds["company_cnpj"] = args.company_cnpj
        return creds

    env_creds = load_env_creds()
    if env_creds:
        if env_creds.get("totp_seed") and not env_creds.get("totp"):
            env_creds["totp"] = generate_totp(env_creds["totp_seed"])
        return env_creds

    die("No credential source found. Use --config, KeePassXC args, or set AGILIZE_USERNAME/AGILIZE_PASSWORD env vars.")


# ─── PKCE + Keycloak login ───────────────────────────────────────────

def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def pkce_pair() -> Tuple[str, str]:
    verifier = b64url(os.urandom(40))
    challenge = b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def extract_forms(text: str) -> List[dict]:
    p = FormParser()
    p.feed(text)
    return p.forms


def pick_form(forms: List[dict], required_names: set) -> dict:
    for form in forms:
        names = {f.get("name", "") for f in form.get("fields", [])}
        if required_names.issubset(names):
            return form
    seen = sorted({f.get("name", "") for form in forms for f in form.get("fields", []) if f.get("name")})
    die(f"could not find form with fields {sorted(required_names)}; seen={seen}")


def hidden_fields(form: dict) -> Dict[str, str]:
    out = {}
    for f in form.get("fields", []):
        name = f.get("name")
        if not name:
            continue
        typ = (f.get("type") or "").lower()
        if typ == "hidden" or name == "credentialId":
            out[name] = f.get("value", "")
    return out


def absolute_action(action: str, current_url: str) -> str:
    resolved = urllib.parse.urljoin(current_url, html.unescape(action or ""))
    parsed = urllib.parse.urlsplit(resolved)
    if parsed.scheme != EXPECTED_SSO_SCHEME or parsed.netloc != EXPECTED_SSO_HOST:
        die("auth form action left expected Agilize SSO origin")
    return resolved


def code_from_url(url: str, expected_state: Optional[str] = None) -> Optional[str]:
    parsed = urllib.parse.urlparse(url)
    pairs = {}
    pairs.update(dict(urllib.parse.parse_qsl(parsed.query)))
    pairs.update(dict(urllib.parse.parse_qsl(parsed.fragment)))
    code = pairs.get("code")
    if code and expected_state and pairs.get("state") and pairs.get("state") != expected_state:
        die("OIDC state mismatch")
    return code


def code_from_response(resp: requests.Response, redirect_uri: str, expected_state: Optional[str] = None) -> Optional[str]:
    if 300 <= resp.status_code < 400 and resp.headers.get("Location"):
        loc = urllib.parse.urljoin(resp.url, resp.headers["Location"])
        if loc.startswith(redirect_uri) or "code=" in loc:
            return code_from_url(loc, expected_state)
    if resp.url and (resp.url.startswith(redirect_uri) or "code=" in resp.url):
        return code_from_url(resp.url, expected_state)
    return None


@dataclass
class LoginResult:
    access_token: str
    expires_in: int
    token_type: str
    obtained_at: int


def login(creds: dict, client_id: str, redirect_uri: str, timeout: int, user_agent: str) -> LoginResult:
    username = creds.get("username", "")
    password = creds.get("password", "")
    totp = creds.get("totp", "")

    if not username:
        die("username is empty")
    if not password:
        die("password is empty")

    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_mode": "fragment",
        "response_type": "code",
        "scope": "openid",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    session = requests.Session()
    session.headers.update({
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    })

    # Step 1: get auth page
    r1 = session.get(AUTH_URL, params=params, timeout=timeout, allow_redirects=True)
    if r1.status_code >= 400:
        die(f"auth page returned HTTP {r1.status_code}")

    # Step 2: submit login form
    form1 = pick_form(extract_forms(r1.text), {"username", "password"})
    data1 = hidden_fields(form1)
    data1.update({"username": username, "password": password})
    for f in form1.get("fields", []):
        if f.get("name") == "login" and f.get("value"):
            data1.setdefault("login", f.get("value", ""))
    action1 = absolute_action(form1.get("action", ""), r1.url)
    r2 = session.post(action1, data=data1, timeout=timeout, allow_redirects=False)

    code = code_from_response(r2, redirect_uri, expected_state=state)

    # Step 3: handle OTP if needed
    if not code:
        otp_html, otp_url = r2.text, r2.url
        if 300 <= r2.status_code < 400 and r2.headers.get("Location"):
            loc = urllib.parse.urljoin(r2.url, r2.headers["Location"])
            if not loc.startswith(redirect_uri):
                r2b = session.get(loc, timeout=timeout, allow_redirects=True)
                otp_html, otp_url = r2b.text, r2b.url
            else:
                code = code_from_url(loc, expected_state=state)

        if not code and totp:
            try:
                form2 = pick_form(extract_forms(otp_html), {"otp"})
            except SystemExit:
                die("OTP form expected but not found; check if 2FA is required and TOTP is configured")
            data2 = hidden_fields(form2)
            data2.update({"otp": totp})
            for f in form2.get("fields", []):
                if f.get("name") == "login":
                    data2["login"] = f.get("value") or "Entrar"
            data2.setdefault("login", "Entrar")
            action2 = absolute_action(form2.get("action", ""), otp_url)
            r3 = session.post(action2, data=data2, timeout=timeout, allow_redirects=False)
            code = code_from_response(r3, redirect_uri, expected_state=state)
            if not code and 300 <= r3.status_code < 400 and r3.headers.get("Location"):
                loc = urllib.parse.urljoin(r3.url, r3.headers["Location"])
                code = code_from_url(loc, expected_state=state)

    if not code:
        die("could not obtain authorization code after login/OTP flow")

    # Step 4: exchange code for token
    token_resp = session.post(TOKEN_URL, data={
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
    }, headers={"Accept": "application/json"}, timeout=timeout)
    if token_resp.status_code >= 400:
        die(f"token exchange returned HTTP {token_resp.status_code}")
    try:
        token_json = token_resp.json()
    except Exception:
        die("token exchange did not return JSON")
    access_token = token_json.get("access_token")
    if not access_token:
        die("token exchange JSON missing access_token")

    return LoginResult(
        access_token=access_token,
        expires_in=int(token_json.get("expires_in") or 0),
        token_type=token_json.get("token_type") or "Bearer",
        obtained_at=int(time.time()),
    )


# ─── API request helper ──────────────────────────────────────────────

def build_api_url(path: str) -> str:
    """Build an authenticated Agilize API URL without allowing cross-origin targets."""
    raw = (path or "").strip()
    if not raw:
        raise ValueError("--api-get path is empty")

    base = urllib.parse.urlsplit(API_BASE)
    parsed = urllib.parse.urlsplit(raw)

    if parsed.scheme or parsed.netloc:
        if parsed.scheme != base.scheme or parsed.netloc != base.netloc:
            raise ValueError("--api-get must target https://app.agilize.com.br or use a relative /api path")
        api_path = parsed.path or "/"
    else:
        api_path = parsed.path
        if not api_path.startswith("/"):
            api_path = "/" + api_path

    if api_path != API_PATH_PREFIX and not api_path.startswith(API_PATH_PREFIX + "/"):
        raise ValueError("--api-get only allows Agilize API paths under /api/")

    return urllib.parse.urlunsplit((base.scheme, base.netloc, api_path, parsed.query, ""))


def api_get(token: LoginResult, path: str, company_cnpj: str, timeout: int) -> requests.Response:
    try:
        url = build_api_url(path)
    except ValueError as exc:
        die(str(exc))
    headers = {
        "Authorization": f"Bearer {token.access_token}",
        "Accept": "application/json",
        "Referer": "https://app.agilize.com.br/",
    }
    if company_cnpj:
        headers["key"] = company_cnpj
    return requests.get(url, headers=headers, timeout=timeout, allow_redirects=False)


def ensure_private_dir(path: Path) -> Path:
    path = path.expanduser()
    if path.exists() and path.is_symlink():
        raise OSError(f"output directory must not be a symlink: {path}")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, stat.S_IRWXU)
    return path


def write_secure(path: str, content: str) -> None:
    p = Path(path).expanduser()
    ensure_private_dir(p.parent)
    if p.exists() and p.is_symlink():
        raise OSError(f"refusing to overwrite symlink: {p}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(str(p), flags, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(content)
    try:
        os.chmod(str(p), stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass


# ─── Main ────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="Login to Agilize via PKCE without printing secrets")
    # Credential sources
    ap.add_argument("--config", help="JSON config file with username/password/totp_secret/company_id/company_cnpj")
    ap.add_argument("--db", help="KeePassXC database path")
    ap.add_argument("--key-file", help="KeePassXC key file path")
    ap.add_argument("--entry", help="KeePassXC entry path (e.g. /Agilize)")
    # Overrides
    ap.add_argument("--company-id", help="Agilize company UUID (overrides config/env)")
    ap.add_argument("--company-cnpj", help="Company CNPJ (digits only, used as 'key' header)")
    ap.add_argument("--client-id", default=DEFAULT_CLIENT_ID)
    ap.add_argument("--redirect-uri", default=DEFAULT_REDIRECT_URI)
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--user-agent", default="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
    # Actions
    ap.add_argument("--verify", action="store_true", help="Run safe verification GET after login")
    ap.add_argument("--api-get", help="Authenticated Agilize API path under /api/ or same-origin https://app.agilize.com.br/api/... URL")
    ap.add_argument("--output", help="Write --api-get response body to this file (mode 0600)")
    args = ap.parse_args()

    creds = resolve_credentials(args)
    company_id = args.company_id or creds.get("company_id", "")
    company_cnpj = args.company_cnpj or creds.get("company_cnpj", "")

    token = login(creds, args.client_id, args.redirect_uri, args.timeout, args.user_agent)
    print(json.dumps({"status": "login_ok", "expires_in": token.expires_in, "token_type": token.token_type}))

    if args.verify:
        if not company_id:
            die("--verify requires --company-id or company_id in credentials")
        path = f"/api/v1/companies/{company_id}/finance-accounts"
        resp = api_get(token, path, company_cnpj, args.timeout)
        ok = 200 <= resp.status_code < 300
        count = None
        if ok:
            try:
                j = resp.json()
                count = len(j) if isinstance(j, list) else (len(j.get("items", [])) if isinstance(j, dict) else None)
            except Exception:
                pass
        print(json.dumps({"status": "verify_ok" if ok else "verify_failed", "http_status": resp.status_code, "item_count": count}))
        if not ok:
            return 1

    if args.api_get:
        resp = api_get(token, args.api_get, company_cnpj, args.timeout)
        body = resp.text
        if args.output:
            write_secure(args.output, body)
            print(json.dumps({"status": "api_get_done", "http_status": resp.status_code, "output": args.output, "bytes": len(body)}))
        else:
            print(json.dumps({"status": "api_get_done", "http_status": resp.status_code, "bytes": len(body), "content_type": resp.headers.get("content-type")}))
        if not (200 <= resp.status_code < 300):
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
