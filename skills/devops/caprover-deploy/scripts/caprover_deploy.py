#!/usr/bin/env python3
"""
CapRover Deploy — automated deployment via CLI → API → Playwright fallback.

Usage:
    python3 caprover_deploy.py --caprover-url URL --app-name APP --repo REPO [--branch main]
    python3 caprover_deploy.py --caprover-url URL --app-name APP --rebuild-only
    python3 caprover_deploy.py --caprover-url URL --app-name APP --tarball ./project.tar

Auth: CAPROVER_PASSWORD env, --keepass-entry, or interactive prompt.
GitHub: GITHUB_TOKEN env, gh auth token, or --github-user + GITHUB_TOKEN env.
"""
import argparse
import json
import os
import subprocess
import sys
import time

import urllib.request
import urllib.error

# ──────────────────────────────────────────────
#  Utilities
# ──────────────────────────────────────────────

class CapRoverAPI:
    """Thin wrapper around CapRover REST API v2."""

    def __init__(self, base_url, token=None):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def _request(self, method, path, payload=None):
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode() if payload else None
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["x-captain-auth"] = self.token
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            resp = urllib.request.urlopen(req, timeout=30)
            body = json.loads(resp.read())
            return body
        except urllib.error.HTTPError as e:
            raw = e.read().decode()[:500]
            return {"status": e.code, "description": raw}
        except Exception as e:
            return {"status": -1, "description": str(e)}

    def login(self, password):
        body = self._request("POST", "/api/v2/login/", {"password": password})
        if body.get("status") == 100:
            self.token = body["data"]["token"]
            return True
        raise RuntimeError(f"Login failed: {body.get('description', body)}")

    def app_exists(self, app_name):
        body = self._request("GET", "/api/v2/user/apps/appDefinitions/")
        defs = body.get("data", {}).get("appDefinitions", [])
        return any(isinstance(a, dict) and a.get("appName") == app_name for a in defs)

    def create_app(self, app_name):
        return self._request("POST", "/api/v2/user/apps/appDefinitions/register/",
                             {"appName": app_name, "hasPersistentData": False})

    def configure_github(self, app_name, repo, branch, gh_user, gh_token):
        payload = {
            "appName": app_name,
            "instanceCount": 1,
            "captainDefinitionRelativeFilePath": "./captain-definition",
            "notExposeAsWebApp": False,
            "forceSsl": False,
            "websocketSupport": False,
            "volumes": [],
            "ports": [],
            "appPushWebhook": {
                "repoInfo": {
                    "user": gh_user,
                    "password": gh_token,
                    "branch": branch,
                    "sshKey": "",
                    "repo": repo,
                }
            },
        }
        return self._request("POST", "/api/v2/user/apps/appDefinitions/update", payload)

    def get_build_status(self, app_name):
        body = self._request("GET", f"/api/v2/user/apps/appData/{app_name}/")
        return body.get("data", {})

    def get_app_definition(self, app_name):
        body = self._request("GET", "/api/v2/user/apps/appDefinitions/")
        defs = body.get("data", {}).get("appDefinitions", [])
        for a in defs:
            if isinstance(a, dict) and a.get("appName") == app_name:
                return a
        return {}

    def wait_for_build(self, app_name, timeout=300, poll_interval=10):
        """Poll build status until done or timeout."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            data = self.get_build_status(app_name)
            building = data.get("isAppBuilding", False)
            failed = data.get("isBuildFailed", False)
            if not building:
                return not failed, data
            remaining = int(deadline - time.time())
            print(f"  Building... ({remaining}s remaining)")
            time.sleep(poll_interval)
        return False, {"error": "Build timeout"}


def get_password(args):
    """Resolve CapRover password from multiple sources (never via CLI args)."""
    if os.environ.get("CAPROVER_PASSWORD"):
        return os.environ["CAPROVER_PASSWORD"]
    if args.keepass_entry:
        # KeePass is optional — requires KEEPASS_DB and KEEPASS_KEY env vars
        kp_db = os.environ.get("KEEPASS_DB")
        kp_key = os.environ.get("KEEPASS_KEY")
        if not kp_db or not kp_key:
            print("  ⚠️ KeePass requires KEEPASS_DB and KEEPASS_KEY env vars")
        else:
            try:
                r = subprocess.run(
                    ["keepassxc-cli", "show", "--show-protected", "-a", "Password",
                     "--no-password", "-k", kp_key, kp_db, args.keepass_entry],
                    capture_output=True, text=True, timeout=20,
                )
                if r.returncode == 0 and r.stdout.strip():
                    return r.stdout.strip()
                print(f"  ⚠️ KeePass lookup failed: {r.stderr.strip()}")
            except FileNotFoundError:
                print("  ⚠️ keepassxc-cli not found")
            except Exception as e:
                print(f"  ⚠️ KeePass error: {e}")
    # Interactive prompt
    import getpass
    return getpass.getpass("CapRover password: ")


def get_github_creds(args):
    """Resolve GitHub credentials (token never via CLI arg — env or gh CLI only)."""
    gh_user = args.github_user or os.environ.get("GITHUB_USER", "")
    gh_token = os.environ.get("GITHUB_TOKEN", "")
    if not gh_token:
        try:
            r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and r.stdout.strip():
                gh_token = r.stdout.strip()
                # Try to get username too
                r2 = subprocess.run(
                    ["gh", "api", "user", "--jq", ".login"],
                    capture_output=True, text=True, timeout=10,
                )
                if r2.returncode == 0:
                    gh_user = gh_user or r2.stdout.strip()
        except FileNotFoundError:
            pass
    return gh_user, gh_token


# ──────────────────────────────────────────────
#  Deploy methods
# ──────────────────────────────────────────────

def try_cli_deploy(args):
    """Method 1: CapRover CLI."""
    print("[CLI] Checking caprover CLI...")
    try:
        r = subprocess.run(["caprover", "--version"], capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            print("  CLI not available or broken")
            return False
    except FileNotFoundError:
        print("  CLI not installed")
        return False

    # Check Node.js version (CLI breaks on Node 26)
    try:
        r = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=5)
        version = r.stdout.strip().lstrip("v")
        major = int(version.split(".")[0])
        if major >= 26:
            print(f"  CLI broken on Node.js {major} (known issue). Skipping.")
            return False
    except Exception:
        pass

    print("  CLI available — deploying...")
    if args.tarball:
        cmd = ["caprover", "deploy", "-t", args.tarball]
    else:
        cmd = ["caprover", "deploy"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode == 0:
        print("  ✅ CLI deploy succeeded")
        return True
    print(f"  ❌ CLI deploy failed: {r.stderr[:200]}")
    return False


def deploy_via_api(api, args, gh_user, gh_token):
    """Method 2: REST API for config (limited — can't trigger Git builds)."""
    print("[API] Configuring app via REST API...")

    # Create app if needed
    if not api.app_exists(args.app_name):
        print(f"  Creating app '{args.app_name}'...")
        result = api.create_app(args.app_name)
        if result.get("status") != 100:
            print(f"  ❌ Create failed: {result.get('description')}")
            return False
        print("  ✅ App created")
    else:
        print(f"  App '{args.app_name}' already exists")

    # Configure GitHub repo
    if args.repo:
        if not gh_token:
            print("  ⚠️ No GitHub token available — skipping repo config")
            print("  ⚠️ You'll need to configure the repo manually in the dashboard")
        else:
            print(f"  Configuring GitHub repo: {args.repo} (branch: {args.branch})")
            result = api.configure_github(args.app_name, args.repo, args.branch, gh_user, gh_token)
            if result.get("status") == 100:
                print("  ✅ GitHub repo configured")
            else:
                print(f"  ⚠️ Config result: {result.get('description', result)}")

    # Note: API cannot trigger Git builds — need Playwright for that
    if not args.tarball and args.repo:
        print("  ℹ️  Git builds require the dashboard 'Force build' button (API limitation)")
        print("  ℹ️  Use --method playwright to trigger the build automatically")
        return "need_playwright"

    return True


def deploy_via_playwright(args, password, gh_user, gh_token):
    """Method 3: Playwright dashboard automation."""
    print("[Playwright] Starting dashboard automation...")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  ❌ Playwright not installed. Run: pip install playwright && playwright install chromium")
        return False

    base_url = args.caprover_url.rstrip("/")
    app = args.app_name

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()

        # Login
        print("  Logging in...")
        page.goto(f"{base_url}/#/login")
        page.wait_for_timeout(2000)
        page.locator('input[type="password"]').fill(password)
        page.locator('button:has-text("Login")').click()
        page.wait_for_timeout(3000)

        # Verify login succeeded (URL should change away from /#/login)
        if "/#/login" in page.url:
            print("  ❌ Login failed — check credentials")
            browser.close()
            return False
        print("  ✅ Logged in")

        # Navigate to app
        page.goto(f"{base_url}/#/apps/details/{app}")
        page.wait_for_timeout(3000)

        # Click Deployment tab
        dep_tab = page.locator("text=Deployment").first
        try:
            dep_tab.click()
            page.wait_for_timeout(2000)
        except Exception:
            # Tab text might be localized
            for tab_text in ["Deployment", "Implantação", "Deploy"]:
                try:
                    page.locator(f"text={tab_text}").first.click()
                    page.wait_for_timeout(2000)
                    break
                except Exception:
                    continue

        # Click Force Build
        force = page.locator("button:has-text('Force Build')")
        if force.count() == 0:
            for btn_text in ["Force build", "Forçar build", "Force Build"]:
                force = page.locator(f"button:has-text('{btn_text}')")
                if force.count() > 0:
                    break

        if force.count() > 0 and not force.is_disabled():
            force.click()
            print("  ✅ Force Build triggered")
        else:
            # Try Save & Restart first, then Force Build
            print("  Force Build disabled — trying Save & Restart first...")
            saves = page.locator("button:has-text('Save & Restart')")
            if saves.count() == 0:
                saves = page.locator("button:has-text('Salvar & Reiniciar')")
            for i in range(saves.count()):
                btn = saves.nth(i)
                if not btn.is_disabled():
                    btn.click()
                    page.wait_for_timeout(3000)
                    break
            force = page.locator("button:has-text('Force Build')")
            if force.count() > 0 and not force.is_disabled():
                force.click()
                print("  ✅ Force Build triggered")
            else:
                print("  ⚠️ Could not trigger build")
                browser.close()
                return False

        page.wait_for_timeout(3000)

        # HTTP Settings — enable HTTPS + WebSocket (unless disabled via flags)
        print("  Configuring HTTP settings...")
        http_tab = page.locator("text=HTTP Settings").first
        if http_tab.count() == 0:
            http_tab = page.locator("text=Configurações HTTP").first
        try:
            http_tab.click()
            page.wait_for_timeout(2000)
        except Exception:
            pass

        # Enable HTTPS (unless --no-https)
        if args.enable_https:
            https_btn = page.locator("button:has-text('Enable HTTPS')")
            if https_btn.count() == 0:
                https_btn = page.locator("button:has-text('Habilitar HTTPS')")
            if https_btn.count() > 0:
                try:
                    if not https_btn.is_disabled():
                        https_btn.click()
                        print("  ✅ HTTPS enabled (waiting for cert...)")
                        page.wait_for_timeout(15000)
                    else:
                        print("  ℹ️  HTTPS already enabled")
                except Exception:
                    print("  ℹ️  HTTPS button not clickable (may already be enabled)")

        # Enable WebSocket (unless --no-websocket)
        if args.enable_websocket:
            ws = page.locator("text=WebSocket Support")
            if ws.count() == 0:
                ws = page.locator("text=Suporte a Websocket")
            if ws.count() > 0:
                # Check if the checkbox is already checked
                ws_parent = ws.locator("..")
                is_checked = False
                try:
                    checkbox = ws_parent.locator("input[type='checkbox']")
                    if checkbox.count() > 0:
                        is_checked = checkbox.is_checked()
                except Exception:
                    pass
                if not is_checked:
                    ws.click()
                    print("  ✅ WebSocket support enabled")
                    page.wait_for_timeout(1000)
                else:
                    print("  ℹ️  WebSocket already enabled")

        # Save
        saves = page.locator("button:has-text('Save & Restart')")
        if saves.count() == 0:
            saves = page.locator("button:has-text('Salvar & Reiniciar')")
        for i in range(saves.count()):
            btn = saves.nth(i)
            if not btn.is_disabled():
                btn.click()
                print(f"  ✅ Settings saved")
                page.wait_for_timeout(5000)
                break

        browser.close()
        return True


def verify_deploy(api, app_name, ssh_cmd=None):
    """Verify deployment succeeded."""
    print("\n[Verify] Checking deployment...")

    # Check build status
    data = api.get_build_status(app_name)
    building = data.get("isAppBuilding", False)
    failed = data.get("isBuildFailed", False)
    if building:
        print("  ⚠️ App still building — waiting...")
        ok, data = api.wait_for_build(app_name)
        if not ok:
            print("  ❌ Build failed!")
            logs = data.get("logs", {}).get("lines", [])
            for l in [x for x in logs if x.strip()][-10:]:
                print(f"    {l}")
            return False
    elif failed:
        print("  ❌ Build previously failed")
        return False

    # Check app definition
    app_def = api.get_app_definition(app_name)
    version = app_def.get("deployedVersion")
    ssl = app_def.get("hasDefaultSubDomainSsl")
    ws = app_def.get("websocketSupport")
    print(f"  Deployed version: {version}")
    print(f"  HTTPS: {'✅' if ssl else '❌'}")
    print(f"  WebSocket: {'✅' if ws else '❌'}")

    # SSH verification (optional)
    if ssh_cmd:
        print(f"  Checking via SSH: docker service ls...")
        r = subprocess.run(
            ssh_cmd + ['docker', 'service', 'ls', '--format', '{{.Name}} {{.Replicas}}'],
            capture_output=True, text=True, timeout=15,
        )
        for line in r.stdout.split("\n"):
            if app_name in line:
                print(f"  Docker: {line.strip()}")
                if "1/1" in line:
                    print("  ✅ Container running (1/1)")
                else:
                    print(f"  ⚠️  Container not healthy: {line.strip()}")
                break

    print("\n  ✅ Deploy verified!")
    return True


# ──────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="CapRover automated deploy (CLI → API → Playwright)")
    parser.add_argument("--caprover-url", required=True, help="CapRover dashboard URL")
    parser.add_argument("--app-name", required=True, help="CapRover app name")
    parser.add_argument("--repo", help="GitHub repo URL")
    parser.add_argument("--branch", default="main", help="Git branch (default: main)")
    parser.add_argument("--tarball", help="Path to tarball file for upload")
    parser.add_argument("--rebuild-only", action="store_true", help="Skip config, just rebuild")
    parser.add_argument("--no-https", action="store_true", help="Skip HTTPS enablement")
    parser.add_argument("--no-websocket", action="store_true", help="Skip WebSocket enablement")
    parser.add_argument("--method", choices=["cli", "api", "playwright", "auto"], default="auto")
    parser.add_argument("--keepass-entry", help="KeePass entry path for password (requires KEEPASS_DB and KEEPASS_KEY env vars)")
    parser.add_argument("--github-user", help="GitHub username")
    parser.add_argument("--ssh-host", help="SSH host for verification (optional)")
    parser.add_argument("--ssh-key", help="SSH key path for verification")
    parser.add_argument("--ssh-port", default="22", help="SSH port")
    parser.add_argument("--ssh-user", help="SSH user")
    parser.add_argument("--timeout", type=int, default=300, help="Build timeout in seconds")
    args = parser.parse_args()

    # Derive enable flags (default: True, negated by --no-* flags)
    args.enable_https = not args.no_https
    args.enable_websocket = not args.no_websocket

    # Resolve credentials
    password = get_password(args)
    gh_user, gh_token = get_github_creds(args)

    # Build SSH command for verification
    ssh_cmd = None
    if args.ssh_host:
        ssh_parts = ["ssh"]
        if args.ssh_key:
            ssh_parts += ["-i", args.ssh_key]
        ssh_parts += ["-p", str(args.ssh_port), f"{args.ssh_user or 'root'}@{args.ssh_host}"]
        ssh_cmd = ssh_parts

    # Authenticate
    api = CapRoverAPI(args.caprover_url)
    print(f"\n{'='*50}")
    print(f"Deploying '{args.app_name}' to {args.caprover_url}")
    print(f"{'='*50}\n")

    print("[Auth] Logging in...")
    api.login(password)
    print("  ✅ Authenticated\n")

    method = args.method
    need_playwright = False

    # ── Method selection ──
    if method in ("auto", "cli"):
        if not args.rebuild_only and try_cli_deploy(args):
            verify_deploy(api, args.app_name, ssh_cmd)
            return
        if method == "cli":
            print("\n❌ CLI method failed. Try --method auto or --method playwright")
            return

    if method in ("auto", "api"):
        result = deploy_via_api(api, args, gh_user, gh_token)
        if result == "need_playwright":
            need_playwright = True
        elif result is False and method == "api":
            print("\n❌ API method failed. Try --method playwright")
            return

    if method in ("auto", "playwright") or need_playwright:
        if not deploy_via_playwright(args, password, gh_user, gh_token):
            if method == "playwright":
                print("\n❌ Playwright method failed.")
                return
        # Wait for build via API
        print("\n[Build] Waiting for build to complete...")
        ok, data = api.wait_for_build(args.app_name, timeout=args.timeout)
        if ok:
            print("  ✅ Build succeeded!")
        else:
            print("  ❌ Build failed!")
            logs_data = data if isinstance(data, dict) else {}
            logs = logs_data.get("logs", {}).get("lines", [])
            for l in [x for x in logs if x.strip()][-10:]:
                print(f"    {l}")
            return

    # Verify
    verify_deploy(api, args.app_name, ssh_cmd)


if __name__ == "__main__":
    main()
