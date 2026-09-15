#!/usr/bin/env python3
"""Bounded CapRover deployment controller; safe plan is the default.

One method is selected before authentication and never falls back after a
possible mutation. Saved sessions are preferred; password login requires the
explicit --allow-login authorization. See the adjacent SKILL.md for the
supported intent/method matrix and lifecycle limits.
"""
import argparse
import base64
import hashlib
import importlib.util
import ipaddress
import copy
import json
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    import urllib.request
    import urllib.error
    import urllib.parse
except ImportError:
    sys.exit("This script requires Python 3 standard library.")

LOCAL_CAPROVER_HOSTS = {"localhost", "127.0.0.1", "::1"}
DEFAULT_GITHUB_REPO_HOST = "github.com"
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
REPO_TOKEN_BINDINGS_ENV = "CAPROVER_REPO_TOKEN_BINDINGS"
GENERIC_GITHUB_TOKEN_ENV_NAMES = {"GITHUB_TOKEN", "GH_TOKEN"}
MAX_API_RESPONSE_BYTES = 1_048_576
MAX_API_ERROR_BYTES = 8_192
MAX_PROTECTED_JSON_BYTES = 1_048_576
SUPPORTED_CLI_VERSION = "2.4.4"
SUPPORTED_NODE_VERSION = "26.7.0"
DEPLOYMENT_GUARD_SHA256 = "6e1bcef46b6367575db593a0d8fd0338bc539a7d97dc5f5a13f3a861b8c54bf7"
APP_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,200}$")
TRUSTED_GIT_EXECUTABLES = (Path("/usr/bin/git"), Path("/bin/git"))
CLI_LAYOUT_HASHES = {
    "package.json": "8c09086e2e4e205ec55fd504516a5c4328ece2080ba7b8f0ef8de121e15754f7",
    "built/commands/caprover.js": "6bc8eb18f5000e85fab08a2c33b6af0a6738af89441190ca2f67cad045393a4d",
    "built/commands/deploy.js": "0f0d9fc524806ddf3731913d5246d010199a1a600b83c4b75c5ab5970e23c2cb",
    "built/api/HttpClient.js": "d96315b81f4a4d963c4be45c79e36d0ecf757cdde112eb6223e918c92ea3e74a",
    "built/api/CliApiManager.js": "7dc23cc2a8a77620d738e95310c4949e5dc0012ccdc4240eaad885b6df927f65",
    "built/api/ApiManager.js": "41c0d7c9548c277894704ce416db5cb9ce75cef892d4c718f3c171da371bba62",
    "built/utils/StorageHelper.js": "6032be2b6195e42894ea3302cd1bca7b43ac3e1dcc1ec97aa21384b3bc176b2f",
    "built/utils/CliHelper.js": "22d58af6ba29c5eeb5333131048c6c91255db028940bd353a67615562dac5f15",
    "built/utils/DeployHelper.js": "6b8408ce612be9f067d6c3279d1efe7d67c3fa1967accfc9d3627e64173b8815",
    "built/utils/ValidationsHandler.js": "d37c12088fc57535f592935bd0b31dff94cc1dc46e9a0d0c9a51f1f6eaf0e307",
}
SSH_USER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SSH_HOST_RE = re.compile(r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
CAPROVER_AUTH_API_STATUS_CODES = frozenset({1105, 1106, 1113, 1114})
CAPROVER_AUTHORIZATION_API_STATUS_CODES = frozenset({1102})
APP_UPDATE_WRITABLE_FIELDS = (
    "projectId",
    "description",
    "instanceCount",
    "captainDefinitionRelativeFilePath",
    "envVars",
    "volumes",
    "tags",
    "nodeId",
    "notExposeAsWebApp",
    "containerHttpPort",
    "httpAuth",
    "forceSsl",
    "ports",
    "customNginxConfig",
    "redirectDomain",
    "preDeployFunction",
    "serviceUpdateOverride",
    "websocketSupport",
    "appDeployTokenConfig",
)
APP_DEFINITION_READ_ONLY_FIELDS = frozenset({
    "appName",
    "hasPersistentData",
    "hasDefaultSubDomainSsl",
    "customDomain",
    "networks",
    "deployedVersion",
    "versions",
    "isAppBuilding",
    "isLegacyAppName",
})
APP_DEFINITION_KNOWN_FIELDS = (
    frozenset(APP_UPDATE_WRITABLE_FIELDS)
    | APP_DEFINITION_READ_ONLY_FIELDS
    | {"appPushWebhook"}
)

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
        resp = None
        try:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}),
                RejectAPIRedirectHandler(),
            )
            resp = opener.open(req, timeout=30)
            body = json.loads(_read_limited_response(resp, MAX_API_RESPONSE_BYTES))
            if not isinstance(body, dict):
                return {"status": -2, "failure": "response"}
            status = body.get("status")
            if isinstance(status, bool) or not isinstance(status, int):
                return {"status": -2, "failure": "response"}
            if status not in {100, 101, 102}:
                return {"status": status, "failure": "api"}
            return body
        except json.JSONDecodeError:
            return {"status": -2, "failure": "response"}
        except urllib.error.HTTPError as e:
            resp = e
            return {"status": e.code, "failure": "http"}
        except CapRoverDeployError as e:
            if e.code == "caprover_response_inconclusive":
                return {"status": -2, "failure": "response"}
            return {"status": -1, "failure": "transport"}
        except Exception:
            return {"status": -1, "failure": "transport"}
        finally:
            if resp is not None:
                try:
                    resp.close()
                except Exception:
                    pass

    def login(self, password):
        body = self._request("POST", "/api/v2/login/", {"password": password})
        data = self._require_ok_data(body)
        token = data.get("token")
        if not isinstance(token, str) or not token:
            raise CapRoverDeployError("caprover_response_inconclusive")
        self.token = token
        return True

    @staticmethod
    def _require_ok_data(body):
        if not isinstance(body, dict):
            raise CapRoverDeployError("caprover_response_inconclusive")
        status = body.get("status")
        if status == -1:
            raise CapRoverDeployError("caprover_network_blocked")
        if status == -2:
            raise CapRoverDeployError("caprover_response_inconclusive")
        if status in ({401} | CAPROVER_AUTH_API_STATUS_CODES):
            raise CapRoverDeployError("caprover_auth_blocked")
        if status in ({403} | CAPROVER_AUTHORIZATION_API_STATUS_CODES):
            raise CapRoverDeployError("caprover_authorization_blocked")
        if status != 100:
            if status is None:
                raise CapRoverDeployError("caprover_response_inconclusive")
            raise CapRoverDeployError("caprover_config_invalid")
        data = body.get("data")
        if not isinstance(data, dict):
            raise CapRoverDeployError("caprover_response_inconclusive")
        return data

    def _get_app_definitions(self):
        body = self._request("GET", "/api/v2/user/apps/appDefinitions/")
        data = self._require_ok_data(body)
        definitions = data.get("appDefinitions")
        if not isinstance(definitions, list):
            raise CapRoverDeployError("caprover_response_inconclusive")
        for app in definitions:
            if not isinstance(app, dict) or not isinstance(app.get("appName"), str) or not app["appName"]:
                raise CapRoverDeployError("caprover_response_inconclusive")
        return definitions

    def app_exists(self, app_name):
        return self.get_app_definition(app_name) is not None

    def create_app(self, app_name):
        return self._request("POST", "/api/v2/user/apps/appDefinitions/register/",
                             {"appName": app_name, "hasPersistentData": False})

    def configure_github(self, app_name, repo, branch, gh_user, gh_token):
        for value in (app_name, repo, branch, gh_user, gh_token):
            if not isinstance(value, str) or not value:
                raise CapRoverDeployError("caprover_config_invalid")

        current = copy.deepcopy(self.get_app_definition(app_name))
        if current is None:
            raise CapRoverDeployError("caprover_config_invalid")
        self._validate_app_definition(current, app_name)

        repo_info = {
            "user": gh_user,
            "password": gh_token,
            "branch": branch,
            "sshKey": "",
            "repo": repo,
        }
        payload = {"appName": app_name}
        for field in APP_UPDATE_WRITABLE_FIELDS:
            if field in current:
                payload[field] = copy.deepcopy(current[field])
        payload["appPushWebhook"] = {"repoInfo": copy.deepcopy(repo_info)}

        result = self._request(
            "POST",
            "/api/v2/user/apps/appDefinitions/update",
            payload,
        )
        self._require_ok_data(result)

        readback = copy.deepcopy(self.get_app_definition(app_name))
        if readback is None:
            raise CapRoverDeployError("caprover_response_inconclusive")
        self._validate_app_definition(readback, app_name)
        if self._canonical_writable_state(current, repo_info) != self._canonical_writable_state(readback):
            raise CapRoverDeployError("caprover_response_inconclusive")
        self._require_immutable_state(current, readback)
        return result

    @staticmethod
    def _validate_app_definition(app, expected_name):
        if not isinstance(app, dict) or set(app) - APP_DEFINITION_KNOWN_FIELDS:
            raise CapRoverDeployError("caprover_response_inconclusive")
        required_types = {
            "appName": str,
            "description": str,
            "instanceCount": int,
            "captainDefinitionRelativeFilePath": str,
            "envVars": list,
            "volumes": list,
            "notExposeAsWebApp": bool,
            "forceSsl": bool,
            "ports": list,
            "websocketSupport": bool,
            "hasPersistentData": bool,
            "hasDefaultSubDomainSsl": bool,
            "customDomain": list,
            "networks": list,
            "deployedVersion": int,
            "versions": list,
        }
        for field, expected_type in required_types.items():
            value = app.get(field)
            if not isinstance(value, expected_type) or (
                expected_type is int and isinstance(value, bool)
            ):
                raise CapRoverDeployError("caprover_response_inconclusive")
        if app["appName"] != expected_name or not app["captainDefinitionRelativeFilePath"]:
            raise CapRoverDeployError("caprover_response_inconclusive")
        if app["instanceCount"] < 0 or app["deployedVersion"] < 0:
            raise CapRoverDeployError("caprover_response_inconclusive")

        string_fields = (
            "projectId",
            "nodeId",
            "customNginxConfig",
            "redirectDomain",
            "preDeployFunction",
            "serviceUpdateOverride",
        )
        for field in string_fields:
            if field in app and not isinstance(app[field], str):
                raise CapRoverDeployError("caprover_response_inconclusive")
        if "containerHttpPort" in app:
            port = app["containerHttpPort"]
            if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port < 65535:
                raise CapRoverDeployError("caprover_response_inconclusive")
        if "isAppBuilding" in app and not isinstance(app["isAppBuilding"], bool):
            raise CapRoverDeployError("caprover_response_inconclusive")
        if "isLegacyAppName" in app and not isinstance(app["isLegacyAppName"], bool):
            raise CapRoverDeployError("caprover_response_inconclusive")

        CapRoverAPI._validate_env_vars(app["envVars"])
        CapRoverAPI._validate_volumes(app["volumes"])
        CapRoverAPI._validate_ports(app["ports"])
        CapRoverAPI._validate_tags(app.get("tags", []))
        CapRoverAPI._validate_domains(app["customDomain"])
        if any(not isinstance(network, str) or not network for network in app["networks"]):
            raise CapRoverDeployError("caprover_response_inconclusive")
        CapRoverAPI._validate_versions(app["versions"])
        CapRoverAPI._validate_http_auth(app.get("httpAuth"))
        CapRoverAPI._validate_deploy_token(app.get("appDeployTokenConfig"))
        CapRoverAPI._validate_push_webhook(app.get("appPushWebhook"))

    @staticmethod
    def _validate_env_vars(values):
        for value in values:
            if (
                not isinstance(value, dict)
                or set(value) != {"key", "value"}
                or not isinstance(value["key"], str)
                or not value["key"]
                or not isinstance(value["value"], str)
            ):
                raise CapRoverDeployError("caprover_response_inconclusive")

    @staticmethod
    def _validate_volumes(values):
        for value in values:
            if not isinstance(value, dict) or set(value) - {"containerPath", "volumeName", "hostPath", "mode"}:
                raise CapRoverDeployError("caprover_response_inconclusive")
            if not isinstance(value.get("containerPath"), str) or not value["containerPath"]:
                raise CapRoverDeployError("caprover_response_inconclusive")
            sources = [value.get("volumeName"), value.get("hostPath")]
            if sum(isinstance(source, str) and bool(source) for source in sources) != 1:
                raise CapRoverDeployError("caprover_response_inconclusive")
            if "mode" in value and not isinstance(value["mode"], str):
                raise CapRoverDeployError("caprover_response_inconclusive")

    @staticmethod
    def _validate_ports(values):
        for value in values:
            if not isinstance(value, dict) or set(value) - {"containerPort", "hostPort", "protocol", "publishMode"}:
                raise CapRoverDeployError("caprover_response_inconclusive")
            for field in ("containerPort", "hostPort"):
                port = value.get(field)
                if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port < 65535:
                    raise CapRoverDeployError("caprover_response_inconclusive")
            if value.get("protocol", "tcp") not in {"tcp", "udp"}:
                raise CapRoverDeployError("caprover_response_inconclusive")
            if value.get("publishMode", "ingress") not in {"ingress", "host"}:
                raise CapRoverDeployError("caprover_response_inconclusive")

    @staticmethod
    def _validate_tags(values):
        if not isinstance(values, list):
            raise CapRoverDeployError("caprover_response_inconclusive")
        for value in values:
            if not isinstance(value, dict) or set(value) != {"tagName"} or not isinstance(value["tagName"], str):
                raise CapRoverDeployError("caprover_response_inconclusive")

    @staticmethod
    def _validate_domains(values):
        for value in values:
            if (
                not isinstance(value, dict)
                or set(value) != {"publicDomain", "hasSsl"}
                or not isinstance(value["publicDomain"], str)
                or not value["publicDomain"]
                or not isinstance(value["hasSsl"], bool)
            ):
                raise CapRoverDeployError("caprover_response_inconclusive")

    @staticmethod
    def _validate_versions(values):
        seen = set()
        for value in values:
            if not isinstance(value, dict) or set(value) - {"version", "deployedImageName", "timeStamp", "gitHash"}:
                raise CapRoverDeployError("caprover_response_inconclusive")
            version = value.get("version")
            if isinstance(version, bool) or not isinstance(version, int) or version < 0 or version in seen:
                raise CapRoverDeployError("caprover_response_inconclusive")
            seen.add(version)
            if not isinstance(value.get("timeStamp"), str):
                raise CapRoverDeployError("caprover_response_inconclusive")
            if "deployedImageName" in value and not isinstance(value["deployedImageName"], str):
                raise CapRoverDeployError("caprover_response_inconclusive")
            if value.get("gitHash") is not None and not isinstance(value.get("gitHash"), str):
                raise CapRoverDeployError("caprover_response_inconclusive")

    @staticmethod
    def _validate_http_auth(value):
        if value is None:
            return
        if (
            not isinstance(value, dict)
            or set(value) != {"user", "passwordHashed"}
            or not isinstance(value["user"], str)
            or not value["user"]
            or not isinstance(value["passwordHashed"], str)
            or not value["passwordHashed"]
        ):
            raise CapRoverDeployError("caprover_response_inconclusive")

    @staticmethod
    def _validate_deploy_token(value):
        if value is None:
            return
        if not isinstance(value, dict) or set(value) - {"enabled", "appDeployToken"} or not isinstance(value.get("enabled"), bool):
            raise CapRoverDeployError("caprover_response_inconclusive")
        token = value.get("appDeployToken")
        if value["enabled"] and (not isinstance(token, str) or not token):
            raise CapRoverDeployError("caprover_response_inconclusive")
        if token is not None and not isinstance(token, str):
            raise CapRoverDeployError("caprover_response_inconclusive")

    @staticmethod
    def _validate_push_webhook(value):
        if value is None:
            return
        if not isinstance(value, dict) or set(value) - {"tokenVersion", "pushWebhookToken", "repoInfo"}:
            raise CapRoverDeployError("caprover_response_inconclusive")
        if not isinstance(value.get("tokenVersion"), str) or not isinstance(value.get("pushWebhookToken"), str):
            raise CapRoverDeployError("caprover_response_inconclusive")
        repo = value.get("repoInfo")
        if not isinstance(repo, dict) or set(repo) - {"repo", "branch", "user", "password", "sshKey"}:
            raise CapRoverDeployError("caprover_response_inconclusive")
        for field in ("repo", "branch", "user", "password"):
            if not isinstance(repo.get(field), str):
                raise CapRoverDeployError("caprover_response_inconclusive")
        if "sshKey" in repo and not isinstance(repo["sshKey"], str):
            raise CapRoverDeployError("caprover_response_inconclusive")

    @staticmethod
    def _canonical_writable_state(app, repo_info=None):
        defaults = {
            "projectId": "",
            "tags": [],
            "nodeId": "",
            "containerHttpPort": 80,
            "httpAuth": None,
            "customNginxConfig": "",
            "redirectDomain": "",
            "preDeployFunction": "",
            "serviceUpdateOverride": "",
            "appDeployTokenConfig": {"enabled": False},
        }
        state = {}
        for field in APP_UPDATE_WRITABLE_FIELDS:
            value = copy.deepcopy(app[field]) if field in app else copy.deepcopy(defaults.get(field))
            if field == "appDeployTokenConfig" and isinstance(value, dict) and not value.get("enabled"):
                value = {"enabled": False}
            state[field] = value
        if repo_info is None:
            webhook = app.get("appPushWebhook") or {}
            repo_info = webhook.get("repoInfo")
        state["repoInfo"] = copy.deepcopy(repo_info)
        return state

    @staticmethod
    def _require_immutable_state(before, after):
        for field in APP_DEFINITION_READ_ONLY_FIELDS - {"isAppBuilding"}:
            if field in before and copy.deepcopy(before[field]) != copy.deepcopy(after.get(field)):
                raise CapRoverDeployError("caprover_response_inconclusive")
        old_webhook = before.get("appPushWebhook")
        new_webhook = after.get("appPushWebhook")
        if old_webhook is not None:
            if new_webhook is None:
                raise CapRoverDeployError("caprover_response_inconclusive")
            for field in ("tokenVersion", "pushWebhookToken"):
                if old_webhook.get(field) != new_webhook.get(field):
                    raise CapRoverDeployError("caprover_response_inconclusive")

    @staticmethod
    def _baseline_version(baseline):
        if baseline is None:
            return None
        value = baseline.get("deployedVersion") if isinstance(baseline, dict) else baseline
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise CapRoverDeployError("caprover_config_invalid")
        return value

    @staticmethod
    def _has_deployment_evidence(app_definition, baseline_version=None):
        if not isinstance(app_definition, dict):
            return False
        version = app_definition.get("deployedVersion")
        versions = app_definition.get("versions")
        if isinstance(version, bool) or not isinstance(version, int) or version <= 0:
            return False
        if baseline_version is not None and version <= baseline_version:
            return False
        if not isinstance(versions, list):
            return False
        matches = [entry for entry in versions if isinstance(entry, dict) and entry.get("version") == version]
        if len(matches) != 1:
            return False
        image = matches[0].get("deployedImageName")
        return isinstance(image, str) and bool(image)

    def get_build_status(self, app_name):
        body = self._request("GET", f"/api/v2/user/apps/appData/{app_name}/")
        data = self._require_ok_data(body)
        building = data.get("isAppBuilding")
        failed = data.get("isBuildFailed")
        if not isinstance(building, bool) or not isinstance(failed, bool):
            raise CapRoverDeployError("caprover_response_inconclusive")
        return {"isAppBuilding": building, "isBuildFailed": failed}

    def get_app_definition(self, app_name):
        matches = [app for app in self._get_app_definitions() if app["appName"] == app_name]
        if len(matches) > 1:
            raise CapRoverDeployError("caprover_response_inconclusive")
        return matches[0] if matches else None

    def preflight(self, app_name, allow_create=False):
        """Sanitized deploy preflight: auth, network, and app visibility."""
        system_info = self._request("GET", "/api/v2/user/system/info/")
        system_data = self._require_ok_data(system_info)
        if (
            not isinstance(system_data.get("hasRootSsl"), bool)
            or not isinstance(system_data.get("forceSsl"), bool)
            or not isinstance(system_data.get("rootDomain"), str)
            or not isinstance(system_data.get("captainSubDomain"), str)
        ):
            raise CapRoverDeployError("caprover_response_inconclusive")

        app_def = self.get_app_definition(app_name)
        if app_def is None and not allow_create:
            raise CapRoverDeployError("caprover_config_invalid")
        return app_def is not None

    def wait_for_build(self, app_name, timeout=300, poll_interval=10, baseline=None):
        """Poll build status until done or timeout."""
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout < 0:
            raise CapRoverDeployError("caprover_config_invalid")
        if isinstance(poll_interval, bool) or not isinstance(poll_interval, (int, float)) or poll_interval <= 0:
            raise CapRoverDeployError("caprover_config_invalid")
        deadline = time.monotonic() + timeout
        baseline_version = self._baseline_version(baseline)
        observed_building = False
        status = {"isAppBuilding": False, "isBuildFailed": False}
        while time.monotonic() < deadline:
            status = self.get_build_status(app_name)
            if status["isBuildFailed"]:
                return False, status
            if status["isAppBuilding"]:
                observed_building = True
            elif observed_building:
                return True, status
            elif baseline_version is not None and self._has_deployment_evidence(
                self.get_app_definition(app_name), baseline_version
            ):
                return True, status
            remaining = max(0, int(deadline - time.monotonic()))
            print(f"  Build pending ({remaining}s remaining)")
            sleep_for = min(poll_interval, max(0, deadline - time.monotonic()))
            if sleep_for:
                time.sleep(sleep_for)
        return False, status


def get_password(args):
    """Resolve CapRover password from multiple sources."""
    if os.environ.get("CAPROVER_PASSWORD"):
        return os.environ["CAPROVER_PASSWORD"]
    if args.keepass_entry:
        try:
            kp_db = os.environ.get("KEEPASS_DB")
            kp_key = os.environ.get("KEEPASS_KEY")
            if not kp_db or not kp_key:
                print("  KeePass requested but KEEPASS_DB and KEEPASS_KEY must be set", file=sys.stderr)
                raise SystemExit(2)
            r = subprocess.run(
                ["keepassxc-cli", "show", "--show-protected", "-a", "Password",
                 "--no-password", "-k", kp_key, kp_db, args.keepass_entry],
                capture_output=True, text=True, timeout=20,
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
            print("  KeePass lookup failed; verify the entry and KeePass config", file=sys.stderr)
        except FileNotFoundError:
            print("  keepassxc-cli not found", file=sys.stderr)
        except Exception:
            print("  KeePass lookup failed", file=sys.stderr)
    # Interactive prompt
    import getpass
    return getpass.getpass("CapRover password: ")


class CapRoverDeployError(RuntimeError):
    def __init__(self, code, message=None):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


def _origin(url):
    parsed = urllib.parse.urlsplit(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise CapRoverDeployError("caprover_config_invalid", "URL has an invalid port") from exc
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), port


def require_same_origin(url, base_url):
    absolute = urllib.parse.urljoin(base_url.rstrip("/") + "/", url)
    parsed = urllib.parse.urlsplit(absolute)
    if parsed.username is not None or parsed.password is not None:
        raise CapRoverDeployError("caprover_network_blocked", "credential-bearing CapRover redirect blocked")
    if _origin(absolute) != _origin(base_url):
        raise CapRoverDeployError("caprover_network_blocked", "cross-origin CapRover redirect blocked")
    return absolute


class SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Allow dashboard redirects only within the configured CapRover origin."""

    def __init__(self, base_url):
        super().__init__()
        self.base_url = base_url

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        safe_url = require_same_origin(newurl, self.base_url)
        return super().redirect_request(req, fp, code, msg, headers, safe_url)


class RejectAPIRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Never retarget a request that may carry a CapRover credential."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def build_ssh_command(host, *, user="root", port="22", key=None):
    host = (host or "").strip()
    user = (user or "root").strip()
    if not SSH_USER_RE.fullmatch(user):
        raise CapRoverDeployError("caprover_config_invalid", "SSH user has an invalid format")
    if host.startswith("-") or "@" in host or not SSH_HOST_RE.fullmatch(host):
        raise CapRoverDeployError("caprover_config_invalid", "SSH host has an invalid format")
    try:
        port_number = int(str(port), 10)
    except (TypeError, ValueError) as exc:
        raise CapRoverDeployError("caprover_config_invalid", "SSH port must be an integer") from exc
    if not 1 <= port_number <= 65535 or str(port).strip() != str(port_number):
        raise CapRoverDeployError("caprover_config_invalid", "SSH port must be in range [1,65535]")
    command = ["ssh"]
    if key:
        command += ["-i", str(key)]
    command += ["-p", str(port_number), "--", f"{user}@{host}"]
    return command


def fail(code, message=None, detail=None, exit_code=1):
    print(code)
    if message:
        print(message)
    if detail:
        print(f"[{detail}]")
    raise SystemExit(exit_code)


def _normalize_env_name(raw_name, label):
    name = (raw_name or "").strip()
    if not name or not ENV_NAME_RE.fullmatch(name):
        raise CapRoverDeployError("caprover_config_invalid", f"{label} must be an environment variable name")
    return name


def _read_limited_response(response, limit):
    """Read an HTTP response only after enforcing its configured byte budget."""
    payload = response.read(limit + 1)
    if len(payload) > limit:
        raise CapRoverDeployError("caprover_response_inconclusive")
    return payload


def _repo_host_key(raw_repo):
    parsed = urllib.parse.urlsplit((raw_repo or "").strip())
    hostname, port = _parsed_host_port(parsed, "Git repo URL")
    return hostname if port is None else f"{hostname}:{port}"


def _repo_token_bindings():
    """Load protected, exact host-to-environment credential bindings."""
    raw = os.environ.get(REPO_TOKEN_BINDINGS_ENV, "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CapRoverDeployError(
            "caprover_config_invalid",
            f"{REPO_TOKEN_BINDINGS_ENV} must be a JSON object",
        ) from exc
    if not isinstance(payload, dict):
        raise CapRoverDeployError(
            "caprover_config_invalid",
            f"{REPO_TOKEN_BINDINGS_ENV} must be a JSON object",
        )
    bindings = {}
    for host, token_env in payload.items():
        if not isinstance(host, str):
            raise CapRoverDeployError("caprover_config_invalid", "repo token binding host must be text")
        hostname, port = _normalize_expected_host(host, REPO_TOKEN_BINDINGS_ENV)
        key = hostname if port is None else f"{hostname}:{port}"
        token_env_name = _normalize_env_name(token_env, REPO_TOKEN_BINDINGS_ENV)
        if token_env_name in GENERIC_GITHUB_TOKEN_ENV_NAMES:
            raise CapRoverDeployError(
                "caprover_config_invalid",
                f"{REPO_TOKEN_BINDINGS_ENV} custom-host bindings must use a host-specific environment variable",
            )
        bindings[key] = token_env_name
    return bindings


def _repo_uses_default_github_host(raw_repo):
    parsed = urllib.parse.urlsplit((raw_repo or "").strip())
    hostname, port = _parsed_host_port(parsed, "Git repo URL")
    return hostname == DEFAULT_GITHUB_REPO_HOST and port is None


def get_github_creds(args):
    """Resolve GitHub credentials."""
    gh_user = args.github_user or os.environ.get("GITHUB_USER", "")
    repo = getattr(args, "repo", None)
    repo_token_env = getattr(args, "repo_token_env", None)

    if repo and not _repo_uses_default_github_host(repo):
        token_env = _repo_token_bindings().get(_repo_host_key(repo))
        if not token_env:
            raise CapRoverDeployError(
                "caprover_config_invalid",
                f"Non-github.com repo URLs require an exact protected binding in {REPO_TOKEN_BINDINGS_ENV}",
            )
        if repo_token_env and _normalize_env_name(repo_token_env, "--repo-token-env") != token_env:
            raise CapRoverDeployError(
                "caprover_config_invalid",
                "--repo-token-env does not match the protected repo host binding",
            )
        token = os.environ.get(token_env, "")
        if not token:
            raise CapRoverDeployError(
                "caprover_config_invalid",
                "protected repo credential is unavailable for this repo host",
            )
        return gh_user, token

    if repo_token_env:
        raise CapRoverDeployError(
            "caprover_config_invalid",
            "--repo-token-env is only an assertion for a protected non-github.com repo binding",
        )

    gh_token = os.environ.get("GITHUB_TOKEN") or ""
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


def _parsed_host_port(parsed, label):
    try:
        port = parsed.port
    except ValueError:
        raise CapRoverDeployError("caprover_config_invalid", f"{label} has an invalid port")
    return (parsed.hostname or "").lower(), port


def _normalize_expected_host(raw_host, label):
    expected = (raw_host or "").strip()
    if not expected:
        return None, None
    expected_for_parse = expected if "://" in expected else f"//{expected}"
    parsed = urllib.parse.urlsplit(expected_for_parse)
    if parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise CapRoverDeployError("caprover_config_invalid", f"{label} must be a hostname or hostname:port")
    hostname, port = _parsed_host_port(parsed, label)
    if not hostname:
        raise CapRoverDeployError("caprover_config_invalid", f"{label} must include a hostname")
    return hostname, port


def is_local_caprover_host(hostname):
    return (hostname or "").lower() in LOCAL_CAPROVER_HOSTS


def validate_caprover_url(raw_url, allow_insecure=False, expected_host=None):
    """Normalize and validate the dashboard URL before any secret is resolved."""
    parsed = urllib.parse.urlsplit((raw_url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise CapRoverDeployError("caprover_config_invalid", "CapRover URL must include http(s) scheme and host")
    if parsed.username or parsed.password:
        raise CapRoverDeployError("caprover_config_invalid", "CapRover URL must not contain credentials")
    hostname, port = _parsed_host_port(parsed, "CapRover URL")
    is_local = is_local_caprover_host(hostname)
    if allow_insecure and not is_local:
        raise CapRoverDeployError("caprover_config_invalid", "--allow-insecure is limited to local/dev CapRover hosts")
    if parsed.scheme != "https" and not allow_insecure:
        raise CapRoverDeployError("caprover_config_invalid", "CapRover URL must use HTTPS; pass --allow-insecure only for local/dev")
    if parsed.scheme != "https" and not is_local:
        raise CapRoverDeployError("caprover_config_invalid", "Non-HTTPS CapRover URLs are limited to local/dev hosts")
    if expected_host:
        expected_hostname, expected_port = _normalize_expected_host(expected_host, "--expected-host")
        if hostname != expected_hostname or port != expected_port:
            raise CapRoverDeployError("caprover_config_invalid", "CapRover URL host does not match --expected-host")
    elif not is_local:
        raise CapRoverDeployError(
            "caprover_config_invalid",
            "CapRover URL requires --expected-host for non-local targets before credentials are resolved",
        )
    if parsed.query or parsed.fragment:
        raise CapRoverDeployError("caprover_config_invalid", "CapRover URL must not include query or fragment")

    path = parsed.path.rstrip("/")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", "")).rstrip("/")


def validate_credential_origin(caprover_url, credential_origin):
    """Bind reusable CapRover credentials to one protected remote origin."""
    target = urllib.parse.urlsplit(caprover_url)
    configured = urllib.parse.urlsplit((credential_origin or "").strip())
    local_target = is_local_caprover_host(target.hostname)
    allowed_schemes = {"https"}
    if local_target:
        allowed_schemes.add("http")
    if (
        configured.scheme not in allowed_schemes
        or not configured.netloc
        or configured.username
        or configured.password
        or configured.path not in {"", "/"}
        or configured.query
        or configured.fragment
    ):
        raise CapRoverDeployError(
            "caprover_config_invalid",
            "Credentials require CAPROVER_CREDENTIAL_ORIGIN set to their exact target origin",
        )

    try:
        target_port = target.port or (443 if target.scheme == "https" else 80)
        configured_port = configured.port or (443 if configured.scheme == "https" else 80)
    except ValueError as exc:
        raise CapRoverDeployError(
            "caprover_config_invalid",
            "CAPROVER_CREDENTIAL_ORIGIN has an invalid port",
        ) from exc
    target_origin = (target.scheme.lower(), (target.hostname or "").lower(), target_port)
    configured_origin = (configured.scheme.lower(), (configured.hostname or "").lower(), configured_port)
    if target_origin != configured_origin:
        raise CapRoverDeployError(
            "caprover_config_invalid",
            "CapRover URL does not match CAPROVER_CREDENTIAL_ORIGIN",
        )
    return True


def validate_github_repo_url(raw_repo, expected_host=None):
    """Normalize and validate a Git repo URL before any GitHub secret is resolved."""
    parsed = urllib.parse.urlsplit((raw_repo or "").strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise CapRoverDeployError("caprover_config_invalid", "GitHub repo URL must use https://host/org/repo")
    if parsed.username or parsed.password:
        raise CapRoverDeployError("caprover_config_invalid", "GitHub repo URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise CapRoverDeployError("caprover_config_invalid", "GitHub repo URL must not include query or fragment")

    segments = [segment for segment in parsed.path.split("/") if segment]
    if len(segments) < 2:
        raise CapRoverDeployError("caprover_config_invalid", "GitHub repo URL must include owner and repo path")

    hostname, port = _parsed_host_port(parsed, "GitHub repo URL")
    if expected_host:
        expected_hostname, expected_port = _normalize_expected_host(expected_host, "--expected-repo-host")
        if hostname != expected_hostname or port != expected_port:
            raise CapRoverDeployError("caprover_config_invalid", "GitHub repo host does not match --expected-repo-host")
    elif hostname != DEFAULT_GITHUB_REPO_HOST or port is not None:
        raise CapRoverDeployError(
            "caprover_config_invalid",
            "GitHub repo URL requires github.com or --expected-repo-host before GitHub credentials are resolved",
        )

    netloc = hostname if port is None else f"{hostname}:{port}"
    path = "/" + "/".join(segments)
    return urllib.parse.urlunsplit(("https", netloc, path, "", ""))


# ──────────────────────────────────────────────
#  Deploy methods
# ──────────────────────────────────────────────

def _write_recovery_snapshot(api, args):
    definition = copy.deepcopy(api.get_app_definition(args.app_name))
    if definition is None:
        raise CapRoverDeployError("caprover_response_inconclusive")
    api._validate_app_definition(definition, args.app_name)
    payload = json.dumps(definition, sort_keys=True, separators=(",", ":")).encode()
    fd = -1
    try:
        fd = os.open(
            args.recovery_snapshot,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        offset = 0
        while offset < len(payload):
            offset += os.write(fd, payload[offset:])
        os.fsync(fd)
        if os.fstat(fd).st_mode & 0o777 != 0o600:
            raise CapRoverDeployError("caprover_config_invalid")
    except CapRoverDeployError:
        raise
    except OSError:
        raise CapRoverDeployError("caprover_config_invalid", "recovery snapshot could not be created") from None
    finally:
        if fd >= 0:
            os.close(fd)


def _configure_remote_git(api, args, gh_user, gh_token):
    if not gh_user or not gh_token:
        raise CapRoverDeployError("caprover_config_invalid", "remote Git credentials are unavailable")
    _write_recovery_snapshot(api, args)
    try:
        result = api.configure_github(args.app_name, args.repo, args.branch, gh_user, gh_token)
        if not isinstance(result, dict) or result.get("status") != 100:
            raise CapRoverDeployError("reconcile_required")
    except Exception:
        raise CapRoverDeployError("reconcile_required") from None
    return True

def _read_guard_events(fd):
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        raw = os.read(fd, 65_537)
    except OSError:
        raise CapRoverDeployError("reconcile_required") from None
    if len(raw) > 65_536:
        raise CapRoverDeployError("reconcile_required")
    events = []
    try:
        for line in raw.splitlines():
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError
            events.append(event)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise CapRoverDeployError("reconcile_required") from None
    return events


def _terminate_cli_process_group(process):
    """Boundedly stop the private CLI process group, including descendants."""
    if process.poll() is not None:
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            return
        except OSError:
            continue
        try:
            process.wait(timeout=1)
            return
        except subprocess.TimeoutExpired:
            continue


def try_cli_deploy(args, session):
    """Run exactly one pinned saved-session CLI deployment behind its request guard."""
    cli_root, node = args.cli_capability
    guard = Path(__file__).with_name("deployment_guard.cjs").resolve(strict=True)
    if hashlib.sha256(guard.read_bytes()).hexdigest() != DEPLOYMENT_GUARD_SHA256:
        raise CapRoverDeployError("capability_unavailable")
    source_mode = "tarball" if args.tarball else "branch"
    cwd = Path(args.source_dir) if args.source_dir else None
    source_path = Path(args.tarball) if args.tarball else cwd / "temporary-captain-to-deploy.tar"
    event_fd = -1
    with tempfile.TemporaryDirectory(prefix="caprover-deploy-") as raw_temp:
        private = Path(raw_temp).resolve()
        private.chmod(0o700)
        config_dir = private / "config" / "configstore"
        config_dir.mkdir(parents=True, mode=0o700)
        config_path = config_dir / "caprover.json"
        registry_bytes = json.dumps({"CapMachines": [copy.deepcopy(session)]}).encode()
        config_fd = os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            offset = 0
            while offset < len(registry_bytes):
                offset += os.write(config_fd, registry_bytes[offset:])
        finally:
            os.close(config_fd)
        event_path = private / "guard-events.jsonl"
        event_fd = os.open(event_path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        policy = {
            "guardVersion": 1,
            "origin": session["baseUrl"],
            "appName": args.app_name,
            "sourceMode": source_mode,
            "sourcePath": str(source_path),
            "authTokenSha256": hashlib.sha256(session["authToken"].encode()).hexdigest(),
            "appTokenSha256": (
                hashlib.sha256(session["appToken"].encode()).hexdigest()
                if session.get("appToken") else None
            ),
        }
        encoded_policy = base64.urlsafe_b64encode(
            json.dumps(policy, separators=(",", ":")).encode()
        ).decode().rstrip("=")
        trusted_path = [str(node.parent)]
        if source_mode == "branch":
            git = args.git_capability
            if str(git.parent) not in trusted_path:
                trusted_path.append(str(git.parent))
        env = {
            "PATH": os.pathsep.join(trusted_path),
            "HOME": str(private),
            "XDG_CONFIG_HOME": str(private / "config"),
            "CI": "1",
            "NO_UPDATE_NOTIFIER": "1",
            "TERM": "dumb",
            "LANG": "C",
            "CAPROVER_DEPLOY_INTERNAL_POLICY": encoded_policy,
            "CAPROVER_DEPLOY_INTERNAL_EVENT_FD": str(event_fd),
        }
        command = [
            str(node), "--require", str(guard),
            str(cli_root / "built/commands/caprover.js"),
            "deploy", "--caproverName", session["name"],
            "--caproverApp", args.app_name,
        ]
        if args.tarball:
            command += ["--tarFile", str(source_path)]
            run_cwd = str(private)
        else:
            command += ["--branch", args.branch]
            run_cwd = str(cwd)
        process = None
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
                cwd=run_cwd,
                pass_fds=(event_fd,),
                start_new_session=True,
            )
            process.wait(timeout=args.timeout)
            events = _read_guard_events(event_fd)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            if process is not None:
                _terminate_cli_process_group(process)
            raise CapRoverDeployError("reconcile_required") from None
        except OSError:
            return False
        finally:
            os.close(event_fd)

    ready = [event for event in events if event.get("type") == "guard_ready"]
    requests = [event for event in events if event.get("type") == "deploy_request"]
    responses = [event for event in events if event.get("type") == "deploy_response"]
    violations = [event for event in events if event.get("type") == "violation"]
    possible_write = bool(requests)
    confirmed = (
        process.returncode == 0
        and len(ready) == 1
        and len(requests) == 1
        and requests[0].get("app") == args.app_name
        and len(responses) == 1
        and responses[0].get("captainStatus") == 101
        and not violations
    )
    if not confirmed and possible_write:
        raise CapRoverDeployError("reconcile_required")
    return confirmed


def deploy_via_api(api, args, gh_user, gh_token):
    """Configure remote Git only; this API path never claims a deployment."""
    _configure_remote_git(api, args, gh_user, gh_token)
    return "configured_not_deployed"


def deploy_via_playwright(args, password, gh_user, gh_token):
    """Trigger exactly one authenticated Force Build for the selected app."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False

    base_url = args.caprover_url.rstrip("/")
    app = args.app_name
    browser = None
    mutation_attempted = False
    route_violation = False
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            # Never use ignore_https_errors=args.allow_insecure; it only permits local HTTP.
            context = browser.new_context(ignore_https_errors=False)
            page = context.new_page()

            def same_origin_route(route, request):
                nonlocal route_violation
                try:
                    require_same_origin(request.url, base_url)
                except CapRoverDeployError:
                    route_violation = True
                    route.abort()
                    return
                route.continue_()

            page.route("**/*", same_origin_route)
            page.goto(f"{base_url}/#/login")
            page.wait_for_timeout(2000)
            if route_violation:
                return False
            require_same_origin(page.url, base_url)
            password_input = page.locator('input[type="password"]')
            login_button = page.locator('button:has-text("Login")')
            if password_input.count() != 1 or login_button.count() != 1:
                return False
            if route_violation:
                return False
            password_input.fill(password)
            if route_violation:
                return False
            login_button.click()
            if route_violation:
                return False
            page.wait_for_timeout(3000)
            if route_violation:
                return False
            require_same_origin(page.url, base_url)
            if page.locator('input[type="password"]').count() != 0:
                return False

            app_url = f"{base_url}/#/apps/details/{app}"
            page.goto(app_url)
            page.wait_for_timeout(3000)
            if route_violation:
                return False
            require_same_origin(page.url, base_url)
            if page.url != app_url:
                return False

            deployment = page.locator("text=Deployment").first
            if deployment.count() != 1 or not deployment.is_visible():
                return False
            deployment.click()
            if route_violation:
                return False
            page.wait_for_timeout(2000)
            if route_violation:
                return False
            force = page.locator("button:has-text('Force Build')")
            if force.count() != 1 or not force.is_visible() or force.is_disabled():
                return False
            if route_violation:
                return False
            mutation_attempted = True
            force.click()
            if route_violation:
                raise CapRoverDeployError("reconcile_required")
            return True
    except Exception:
        if mutation_attempted:
            raise CapRoverDeployError("reconcile_required") from None
        return False
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass


def verify_deploy(api, app_name, ssh_cmd=None, baseline=None):
    """Verify deployment evidence without claiming application health."""
    print("\n[Verify] Checking deployment evidence...")
    try:
        baseline_version = CapRoverAPI._baseline_version(baseline)
        status = api.get_build_status(app_name)
        if (
            not isinstance(status, dict)
            or not isinstance(status.get("isAppBuilding"), bool)
            or not isinstance(status.get("isBuildFailed"), bool)
        ):
            raise CapRoverDeployError("caprover_response_inconclusive")
        if status["isBuildFailed"]:
            print("  Deployment evidence unavailable: build failed")
            return False
        if status["isAppBuilding"]:
            print("  Build is still pending")
            ok, status = api.wait_for_build(app_name, baseline=baseline)
            if not ok:
                print("  Deployment evidence unavailable: build not confirmed")
                return False

        app_definition = api.get_app_definition(app_name)
        if not CapRoverAPI._has_deployment_evidence(app_definition, baseline_version):
            print("  Deployment evidence unavailable: generation not confirmed")
            return False
        print("  Deployment generation and image reference confirmed")

        if ssh_cmd:
            desired = app_definition.get("instanceCount") if isinstance(app_definition, dict) else None
            if isinstance(desired, bool) or not isinstance(desired, int) or desired <= 0:
                print("  Deployment evidence unavailable: replica target invalid")
                return False
            service_name = f"srv-captain--{app_name}"
            try:
                result = subprocess.run(
                    ssh_cmd
                    + [
                        "docker",
                        "service",
                        "ls",
                        "--filter",
                        f"name={service_name}",
                        "--format",
                        "{{.Name}}\t{{.Replicas}}",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
            except Exception:
                print("  Deployment evidence unavailable: replica check failed")
                return False
            if result.returncode != 0 or not isinstance(result.stdout, str):
                print("  Deployment evidence unavailable: replica check failed")
                return False
            replicas = []
            for line in result.stdout.splitlines():
                match = re.fullmatch(r"(\S+)\s+([0-9]+)/([0-9]+)", line.strip())
                if match and match.group(1) == service_name:
                    replicas.append((int(match.group(2)), int(match.group(3))))
            if len(replicas) != 1 or replicas[0] != (desired, desired):
                print("  Deployment evidence unavailable: replica count mismatch")
                return False
            print("  Intended replica count confirmed")

        print("  Deployment evidence verified; application health not proven")
        return True
    except Exception:
        print("  Deployment evidence inconclusive")
        return False


# ──────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────

def build_arg_parser():
    parser = argparse.ArgumentParser(description="CapRover deployment controller (safe plan by default)")
    parser.add_argument("--caprover-url", required=True, help="CapRover dashboard URL")
    parser.add_argument("--app-name", required=True, help="CapRover app name")
    parser.add_argument("--repo", help="GitHub repo URL")
    parser.add_argument("--branch", help="Explicit Git branch for --repo or --source-dir")
    parser.add_argument("--tarball", help="Path to tarball file for upload")
    parser.add_argument("--source-dir", help="Explicit local Git checkout used with --branch")
    parser.add_argument("--rebuild-only", action="store_true", help="Skip config, just rebuild")
    parser.add_argument("--configure-only", action="store_true", help="Configure remote Git without claiming deployment")
    parser.add_argument("--apply", action="store_true", help="Authorize the selected deploy/config mutation")
    parser.add_argument("--allow-create", action="store_true", help="Authorize creating a missing app")
    parser.add_argument("--allow-login", action="store_true", help="Authorize password resolution and login")
    parser.add_argument("--enable-https", action="store_true", default=False, help="Request separate HTTPS operation")
    parser.add_argument("--enable-websocket", action="store_true", default=False, help="Request separate WebSocket operation")
    parser.add_argument("--method", choices=["cli", "api", "playwright", "auto"], default="auto")
    parser.add_argument("--keepass-entry", help="KeePass entry path for password")
    parser.add_argument("--github-user", help="GitHub username")
    parser.add_argument(
        "--repo-token-env",
        help="Optional assertion that must match the protected non-github.com repo token binding",
    )
    parser.add_argument("--expected-host", help="Required hostname assertion for non-local CapRover targets")
    parser.add_argument("--expected-repo-host", help="Required Git repo hostname assertion when --repo is not github.com")
    parser.add_argument("--allow-insecure", action="store_true", help="Allow non-HTTPS/self-signed local/dev CapRover targets")
    parser.add_argument("--caprover-name", help="Exact saved CapRover session alias")
    parser.add_argument("--targets", help="Protected alias-to-origin binding JSON")
    parser.add_argument("--registry", help="Protected CapRover CLI registry JSON")
    parser.add_argument("--cli-root", help="Trusted CapRover CLI 2.4.4 installation root")
    parser.add_argument("--node", help="Pinned Node executable")
    parser.add_argument("--recovery-snapshot", help="Explicit private path outside Git for pre-config recovery data")
    parser.add_argument("--ssh-host", help="SSH host for verification (optional)")
    parser.add_argument("--ssh-key", help="SSH key path for verification")
    parser.add_argument("--ssh-port", default="22", help="SSH port")
    parser.add_argument("--ssh-user", help="SSH user")
    parser.add_argument("--timeout", type=int, default=300, help="Build timeout in seconds")
    return parser


def _validate_intent_and_select_method(args):
    if isinstance(args.timeout, bool) or not isinstance(args.timeout, int) or not 1 <= args.timeout <= 3600:
        raise CapRoverDeployError("caprover_config_invalid", "--timeout must be in range [1,3600]")
    sources = sum(bool(value) for value in (args.repo, args.tarball, args.source_dir, args.rebuild_only))
    if sources != 1:
        raise CapRoverDeployError("caprover_config_invalid", "select exactly one deployment source")
    if args.repo and not args.branch:
        raise CapRoverDeployError("caprover_config_invalid", "--repo requires --branch")
    if args.source_dir and not args.branch:
        raise CapRoverDeployError("caprover_config_invalid", "--source-dir requires --branch")
    if args.branch and not (args.repo or args.source_dir):
        raise CapRoverDeployError("caprover_config_invalid", "--branch requires --repo or --source-dir")
    if args.configure_only and not args.repo:
        raise CapRoverDeployError("caprover_config_invalid", "--configure-only requires --repo")
    if not args.ssh_host and (args.ssh_key or args.ssh_user):
        raise CapRoverDeployError("caprover_config_invalid", "SSH options require --ssh-host")
    if args.enable_https or args.enable_websocket:
        raise CapRoverDeployError(
            "capability_unavailable",
            "HTTPS and WebSocket changes require a separate authorized operation",
        )

    compatible = {
        "cli": bool(args.tarball or args.source_dir) and not args.configure_only,
        "api": bool(args.repo and args.configure_only),
        "playwright": bool((args.repo or args.rebuild_only) and not args.configure_only),
    }
    if args.method == "auto":
        if args.tarball or args.source_dir:
            method = "cli"
        elif args.configure_only:
            method = "api"
        else:
            method = "playwright"
    else:
        method = args.method
    if not compatible[method]:
        raise CapRoverDeployError("caprover_config_invalid", "selected method cannot perform the requested intent")
    return method


def _validate_branch(branch):
    if (
        not isinstance(branch, str)
        or not BRANCH_RE.fullmatch(branch)
        or branch.startswith("-")
        or ".." in branch
        or "//" in branch
        or "@{" in branch
        or branch.endswith(("/", ".", ".lock"))
    ):
        raise CapRoverDeployError("caprover_config_invalid", "branch has an unsafe format")


def _trusted_git_capability():
    """Resolve Git only from fixed system locations with non-writable ancestry."""
    for candidate in TRUSTED_GIT_EXECUTABLES:
        try:
            resolved = candidate.resolve(strict=True)
            executable_info = resolved.stat()
            directory_info = resolved.parent.stat()
        except OSError:
            continue
        if (
            resolved.is_file()
            and os.access(resolved, os.X_OK)
            and executable_info.st_uid == 0
            and not executable_info.st_mode & 0o022
            and directory_info.st_uid == 0
            and not directory_info.st_mode & 0o022
        ):
            return resolved
    raise CapRoverDeployError("capability_unavailable", "trusted Git executable is unavailable")


def _trusted_cli_capability(args):
    if not args.cli_root or not args.node:
        raise CapRoverDeployError("capability_unavailable", "CLI method requires --cli-root and --node")
    try:
        cli_root = Path(args.cli_root).resolve(strict=True)
        node = Path(args.node).resolve(strict=True)
        package = json.loads((cli_root / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        raise CapRoverDeployError("capability_unavailable", "trusted CLI installation is unavailable") from None
    if (
        not cli_root.is_dir()
        or not node.is_file()
        or not os.access(node, os.X_OK)
        or not isinstance(package, dict)
        or package.get("name") != "caprover"
        or package.get("version") != SUPPORTED_CLI_VERSION
    ):
        raise CapRoverDeployError("capability_unavailable", "trusted CLI installation is incompatible")
    for relative, expected in CLI_LAYOUT_HASHES.items():
        try:
            actual = hashlib.sha256((cli_root / relative).read_bytes()).hexdigest()
        except OSError:
            raise CapRoverDeployError("capability_unavailable", "trusted CLI installation is incomplete") from None
        if actual != expected:
            raise CapRoverDeployError("capability_unavailable", "trusted CLI installation is incompatible")
    try:
        completed = subprocess.run(
            [str(node), "-p", "process.versions.node"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            env={"PATH": str(node.parent), "HOME": "/nonexistent", "CI": "1"},
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise CapRoverDeployError("capability_unavailable", "pinned Node runtime is unavailable") from None
    if completed.returncode or completed.stdout.strip() != SUPPORTED_NODE_VERSION:
        raise CapRoverDeployError("capability_unavailable", "pinned Node runtime is incompatible")
    return cli_root, node


def _validate_source_capability(args, method):
    if not APP_NAME_RE.fullmatch(args.app_name or ""):
        raise CapRoverDeployError("caprover_config_invalid", "app name has an unsafe format")
    if args.branch:
        _validate_branch(args.branch)
    if args.repo:
        if not args.recovery_snapshot:
            raise CapRoverDeployError("caprover_config_invalid", "remote Git configuration requires --recovery-snapshot")
        snapshot = Path(args.recovery_snapshot)
        if not snapshot.is_absolute() or snapshot.exists():
            raise CapRoverDeployError("caprover_config_invalid", "recovery snapshot must be a new absolute path")
        try:
            parent = snapshot.parent.resolve(strict=True)
        except OSError:
            raise CapRoverDeployError("caprover_config_invalid", "recovery snapshot parent is unavailable") from None
        if any((candidate / ".git").exists() for candidate in (parent, *parent.parents)):
            raise CapRoverDeployError("caprover_config_invalid", "recovery snapshot must be outside Git")
        args.recovery_snapshot = str(parent / snapshot.name)
    if args.tarball:
        try:
            source = Path(args.tarball).resolve(strict=True)
            info = source.lstat()
        except OSError:
            raise CapRoverDeployError("caprover_config_invalid", "tarball is unavailable") from None
        if not stat.S_ISREG(info.st_mode) or source.is_symlink() or info.st_size <= 0:
            raise CapRoverDeployError("caprover_config_invalid", "tarball must be a nonempty regular file")
        args.tarball = str(source)
    if args.source_dir:
        try:
            source_dir = Path(args.source_dir).resolve(strict=True)
        except OSError:
            raise CapRoverDeployError("caprover_config_invalid", "source directory is unavailable") from None
        if not source_dir.is_dir() or (source_dir / "temporary-captain-to-deploy.tar").exists():
            raise CapRoverDeployError("caprover_config_invalid", "source directory is not safe for CLI archive")
        git = _trusted_git_capability()
        results = []
        for command in (
            [str(git), "-C", str(source_dir), "rev-parse", "--show-toplevel"],
            [str(git), "-C", str(source_dir), "rev-parse", "--verify", f"{args.branch}^{{commit}}"],
        ):
            try:
                result = subprocess.run(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=10,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                raise CapRoverDeployError("capability_unavailable", "local Git source cannot be validated") from None
            if result.returncode:
                raise CapRoverDeployError("caprover_config_invalid", "local Git source or branch is invalid")
            results.append(result)
        try:
            checkout_root = Path(results[0].stdout.strip()).resolve(strict=True)
        except OSError:
            raise CapRoverDeployError("caprover_config_invalid", "local Git source root is invalid") from None
        if checkout_root != source_dir:
            raise CapRoverDeployError("caprover_config_invalid", "--source-dir must be the Git checkout root")
        args.source_dir = str(source_dir)
        args.git_capability = git
    if method == "cli":
        guard = Path(__file__).with_name("deployment_guard.cjs")
        try:
            guard_hash = hashlib.sha256(guard.read_bytes()).hexdigest()
        except OSError:
            raise CapRoverDeployError("capability_unavailable", "deployment guard is unavailable") from None
        if guard_hash != DEPLOYMENT_GUARD_SHA256:
            raise CapRoverDeployError("capability_unavailable", "deployment guard is incompatible")
        args.cli_capability = _trusted_cli_capability(args)
    elif method == "playwright":
        try:
            available = importlib.util.find_spec("playwright.sync_api") is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            available = False
        if not available:
            raise CapRoverDeployError("capability_unavailable", "Playwright is unavailable")


def _reject_duplicate_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate key")
        value[key] = item
    return value


def _read_protected_json(raw_path):
    path = Path(raw_path)
    if not path.is_absolute():
        raise CapRoverDeployError("caprover_config_invalid", "session files must use absolute paths")
    fd = -1
    try:
        path = path.parent.resolve(strict=True) / path.name
        for parent in (path.parent, *path.parent.parents):
            try:
                (parent / ".git").lstat()
            except FileNotFoundError:
                continue
            except OSError:
                raise CapRoverDeployError(
                    "caprover_config_invalid", "session files must be outside Git"
                ) from None
            raise CapRoverDeployError(
                "caprover_config_invalid", "session files must be outside Git"
            )
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode):
            raise CapRoverDeployError("caprover_config_invalid", "session file permissions are unsafe")
        fd = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
        )
        info = os.fstat(fd)
        if (
            (before.st_dev, before.st_ino) != (info.st_dev, info.st_ino)
            or not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or info.st_size > MAX_PROTECTED_JSON_BYTES
        ):
            raise CapRoverDeployError("caprover_config_invalid", "session file permissions are unsafe")
        data = os.read(fd, MAX_PROTECTED_JSON_BYTES + 1)
        if len(data) > MAX_PROTECTED_JSON_BYTES or os.read(fd, 1):
            raise CapRoverDeployError("caprover_config_invalid", "session file is too large")
        value = json.loads(data, object_pairs_hook=_reject_duplicate_keys)
    except CapRoverDeployError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise CapRoverDeployError("caprover_config_invalid", "session configuration is invalid") from None
    finally:
        if fd >= 0:
            os.close(fd)
    if not isinstance(value, dict):
        raise CapRoverDeployError("caprover_config_invalid", "session configuration is invalid")
    return value


def _session_origin(value, allow_insecure=False):
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 2048
        or value != value.strip()
        or any(character.isspace() or ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        raise CapRoverDeployError("caprover_config_invalid", "saved session origin is invalid")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        raise CapRoverDeployError("caprover_config_invalid", "saved session origin is invalid") from None
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.scheme != parsed.scheme.lower()
        or not parsed.netloc
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise CapRoverDeployError("caprover_config_invalid", "saved session origin is invalid")
    hostname = parsed.hostname
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        if any(
            not label
            or len(label) > 63
            or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", label)
            for label in hostname.split(".")
        ):
            raise CapRoverDeployError("caprover_config_invalid", "saved session origin is invalid") from None
    if port is not None and not 1 <= port <= 65535:
        raise CapRoverDeployError("caprover_config_invalid", "saved session origin is invalid")
    if parsed.scheme == "http" and (not allow_insecure or not is_local_caprover_host(parsed.hostname)):
        raise CapRoverDeployError("caprover_config_invalid", "saved session origin is insecure")
    scheme, host, port = _origin(value)
    rendered_host = f"[{host}]" if ":" in host else host
    default_port = 443 if scheme == "https" else 80
    return f"{scheme}://{rendered_host}{f':{port}' if port != default_port else ''}"


def load_saved_session(args):
    targets = _read_protected_json(args.targets)
    registry = _read_protected_json(args.registry)
    if targets.get("version") != 1 or type(targets.get("version")) is not int:
        raise CapRoverDeployError("caprover_config_invalid", "target binding schema is invalid")
    bindings = targets.get("targets")
    machines = registry.get("CapMachines")
    if not isinstance(bindings, list) or not isinstance(machines, list) or not APP_NAME_RE.fullmatch(args.caprover_name or ""):
        raise CapRoverDeployError("caprover_config_invalid", "saved session schema is invalid")
    if any(
        not isinstance(item, dict)
        or set(item) != {"alias", "origin"}
        or not isinstance(item.get("alias"), str)
        or not APP_NAME_RE.fullmatch(item["alias"])
        or not isinstance(item.get("origin"), str)
        or not item["origin"]
        for item in bindings
    ):
        raise CapRoverDeployError("caprover_config_invalid", "target binding schema is invalid")
    if any(
        not isinstance(item, dict)
        or not isinstance(item.get("name"), str)
        or not APP_NAME_RE.fullmatch(item["name"])
        for item in machines
    ):
        raise CapRoverDeployError("caprover_config_invalid", "registry schema is invalid")
    selected_bindings = [item for item in bindings if item["alias"] == args.caprover_name]
    selected_machines = [item for item in machines if item["name"] == args.caprover_name]
    if len(selected_bindings) != 1 or len(selected_machines) != 1:
        raise CapRoverDeployError("caprover_config_invalid", "saved session binding is ambiguous")
    origin = _session_origin(selected_bindings[0]["origin"], args.allow_insecure)
    registry_origin = _session_origin(selected_machines[0].get("baseUrl"), args.allow_insecure)
    supplied_origin = _session_origin(args.caprover_url, args.allow_insecure)
    if origin != registry_origin or origin != supplied_origin:
        raise CapRoverDeployError("caprover_config_invalid", "saved session origin does not match target")
    token = selected_machines[0].get("authToken")
    if not isinstance(token, str) or not token or len(token) > 8192:
        raise CapRoverDeployError("caprover_config_invalid", "saved session token is invalid")
    snapshot = {"name": args.caprover_name, "baseUrl": origin, "authToken": token}
    app_token = selected_machines[0].get("appToken")
    if app_token is not None:
        if not isinstance(app_token, str) or len(app_token) > 8192:
            raise CapRoverDeployError("caprover_config_invalid", "saved session token is invalid")
        snapshot["appToken"] = app_token
    return snapshot


def main(argv=None):
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        args.caprover_url = validate_caprover_url(
            args.caprover_url,
            allow_insecure=args.allow_insecure,
            expected_host=args.expected_host,
        )
    except CapRoverDeployError as e:
        fail(e.code, e.message, detail="url validation", exit_code=2)
    if args.repo:
        try:
            args.repo = validate_github_repo_url(args.repo, expected_host=args.expected_repo_host)
        except CapRoverDeployError as e:
            fail(e.code, e.message, detail="repo validation", exit_code=2)
    try:
        args.selected_method = _validate_intent_and_select_method(args)
        _validate_source_capability(args, args.selected_method)
    except CapRoverDeployError as e:
        fail(e.code, e.message, detail="intent validation", exit_code=2)
    if args.allow_insecure:
        print("  ⚠️  Insecure CapRover target allowed for local/dev use only")

    if not args.apply:
        print(f"deployment_plan method={args.selected_method} apply_required")
        return 0
    session_fields = (args.caprover_name, args.targets, args.registry, args.cli_root, args.node)
    has_session = all(session_fields)
    if any(session_fields) and not has_session:
        fail("caprover_config_invalid", "saved session arguments must be supplied together", detail="session validation", exit_code=2)
    if args.selected_method == "cli" and not has_session:
        fail("caprover_config_invalid", "CLI deploy requires a complete saved session binding", detail="session validation", exit_code=2)
    if args.selected_method == "playwright" and not args.allow_login:
        fail("caprover_config_invalid", "Playwright requires explicit --allow-login", detail="authentication policy", exit_code=2)
    if not has_session and not args.allow_login:
        fail("caprover_config_invalid", "apply requires a saved session or explicit --allow-login", detail="authentication policy", exit_code=2)

    ssh_cmd = None
    if args.ssh_host:
        try:
            ssh_cmd = build_ssh_command(
                args.ssh_host,
                user=args.ssh_user or "root",
                port=args.ssh_port,
                key=args.ssh_key,
            )
        except CapRoverDeployError as e:
            fail(e.code, e.message, detail="SSH validation", exit_code=2)

    session = None
    password = None
    if has_session:
        try:
            session = load_saved_session(args)
            api = CapRoverAPI(args.caprover_url, token=session["authToken"])
        except CapRoverDeployError as e:
            fail(e.code, "Saved session validation failed", detail="session validation", exit_code=2)
    else:
        try:
            validate_credential_origin(args.caprover_url, os.environ.get("CAPROVER_CREDENTIAL_ORIGIN"))
        except CapRoverDeployError as e:
            fail(e.code, e.message, detail="credential origin validation", exit_code=2)

    gh_user = ""
    gh_token = ""
    if args.repo:
        try:
            gh_user, gh_token = get_github_creds(args)
        except CapRoverDeployError as e:
            fail(e.code, e.message, detail="repo token validation", exit_code=2)

    if not has_session:
        try:
            password = get_password(args)
            api = CapRoverAPI(args.caprover_url)
            api.login(password)
        except SystemExit:
            raise
        except CapRoverDeployError as e:
            fail(e.code, "CapRover authentication failed", detail="authentication failed")
        except Exception:
            fail("caprover_auth_blocked", "CapRover authentication blocked", detail="authentication failed")
    if args.selected_method == "playwright" and password is None:
        try:
            validate_credential_origin(args.caprover_url, os.environ.get("CAPROVER_CREDENTIAL_ORIGIN"))
        except CapRoverDeployError as e:
            fail(e.code, e.message, detail="credential origin validation", exit_code=2)
        try:
            password = get_password(args)
        except SystemExit:
            raise
        except Exception:
            fail("caprover_auth_blocked", "CapRover authentication blocked", detail="password resolution")
    mutation_attempted = False
    try:
        app_exists = api.preflight(args.app_name, allow_create=args.allow_create)
        if not app_exists:
            if not args.allow_create:
                raise CapRoverDeployError("caprover_config_invalid")
            try:
                mutation_attempted = True
                api._require_ok_data(api.create_app(args.app_name))
                created = api.get_app_definition(args.app_name)
                if created is None:
                    raise CapRoverDeployError("reconcile_required")
                api._validate_app_definition(created, args.app_name)
            except Exception:
                raise CapRoverDeployError("reconcile_required") from None
    except SystemExit:
        raise
    except CapRoverDeployError as e:
        fail(e.code, "CapRover preflight blocked", detail="sanitized preflight")
    except Exception:
        fail("caprover_response_inconclusive", "CapRover preflight blocked", detail="sanitized preflight")

    if args.selected_method == "api":
        try:
            result = deploy_via_api(api, args, gh_user, gh_token)
            mutation_attempted = True
        except CapRoverDeployError as e:
            if e.code == "reconcile_required" or mutation_attempted:
                fail("reconcile_required", "Configuration state requires reconciliation", detail="possible write")
            fail(e.code, "Remote Git configuration was not confirmed", detail="configuration")
        except Exception:
            fail("reconcile_required", "Configuration state requires reconciliation", detail="possible write")
        if result != "configured_not_deployed":
            fail("caprover_config_invalid", "API configuration was not confirmed", detail="API method")
        print("configured_not_deployed")
        return 0

    if args.repo:
        try:
            _configure_remote_git(api, args, gh_user, gh_token)
            mutation_attempted = True
        except CapRoverDeployError as e:
            if e.code == "reconcile_required" or mutation_attempted:
                fail("reconcile_required", "Configuration state requires reconciliation", detail="possible write")
            fail(e.code, "Remote Git configuration was not confirmed", detail="configuration")
        except Exception:
            fail("reconcile_required", "Configuration state requires reconciliation", detail="possible write")

    try:
        baseline = api.get_app_definition(args.app_name)
        if baseline is None:
            raise CapRoverDeployError("caprover_response_inconclusive")
        api._validate_app_definition(baseline, args.app_name)
    except Exception:
        if mutation_attempted:
            fail("reconcile_required", "Deployment state requires reconciliation", detail="possible write")
        fail("caprover_response_inconclusive", "Deployment baseline unavailable", detail="baseline")

    try:
        if args.selected_method == "cli":
            triggered = try_cli_deploy(args, session)
        else:
            triggered = deploy_via_playwright(args, password, gh_user, gh_token)
    except CapRoverDeployError as e:
        if e.code == "reconcile_required" or mutation_attempted:
            fail("reconcile_required", "Deployment state requires reconciliation", detail="possible write")
        fail(e.code, "Selected deployment trigger failed", detail="selected method")
    except Exception:
        fail("reconcile_required", "Deployment state requires reconciliation", detail="possible write")
    if not triggered and mutation_attempted:
        fail("reconcile_required", "Deployment state requires reconciliation", detail="possible write")
    if not triggered:
        fail("deployment_trigger_failed", "Selected deployment trigger failed", detail="selected method")
    try:
        ok, _ = api.wait_for_build(args.app_name, timeout=args.timeout, baseline=baseline)
    except Exception:
        fail("reconcile_required", "Deployment state requires reconciliation", detail="possible write")
    if not ok:
        fail("reconcile_required", "Deployment state requires reconciliation", detail="possible write")
    if not verify_deploy(api, args.app_name, ssh_cmd, baseline=baseline):
        fail("reconcile_required", "Deployment evidence was not verified", detail="possible write")
    print("deployment_evidence_verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
