"""Policy and normalization primitives; no organization-specific defaults."""

import hashlib
import json
import re
import stat
from pathlib import Path
import unicodedata


def normalize(value):
    value = unicodedata.normalize(
        "NFKD", unicodedata.normalize("NFKC", value).casefold()
    )
    return "".join(c for c in value if c.isalnum())


def digest(domain, value):
    return hashlib.sha256((domain + "\0" + value).encode("utf-8")).hexdigest()


def context_digest(value, term, location="content"):
    return digest(
        "clean-room-context/v1",
        location + "\0" + normalize(term) + "\0" + normalize(value),
    )


POLICY_BYTES = 1024 * 1024
MAX_RULES = 256
MAX_ENTRIES = 10000
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_DEPTH = 3
MAX_PATH = 1024
MAX_FINDINGS = 10000
MAX_LINES = 100000


class InvalidInput(ValueError):
    """A closed, deliberately non-diagnostic input failure."""


def require(condition):
    if not condition:
        raise InvalidInput()


def fields(value, names):
    require(type(value) is dict and set(value) == set(names.split()))


def string(value, minimum=1, maximum=1024):
    require(type(value) is str and minimum <= len(value) <= maximum)
    require(value == value.strip())
    require(not any(unicodedata.category(c).startswith("C") for c in value))
    return value


def relative_path(value):
    string(value, maximum=MAX_PATH)
    require(not any(c in value for c in "\\:*?[]!"))
    require(
        all(
            part not in ("", ".", "..") and part == part.strip()
            for part in value.split("/")
        )
    )
    return value


def sha(value):
    require(type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def reject_constant(value):
    raise InvalidInput()


def load_policy(root, path):
    path = Path(path)
    require(path.is_absolute())
    info = path.lstat()
    require(
        stat.S_ISREG(info.st_mode)
        and info.st_nlink == 1
        and info.st_size <= POLICY_BYTES
    )
    require(not path.resolve().is_relative_to(root.resolve()))
    with path.open("rb") as stream:
        raw = stream.read(POLICY_BYTES + 1)
    require(len(raw) <= POLICY_BYTES)
    policy = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=unique_object,
        parse_constant=reject_constant,
    )
    fields(policy, "schema_version deny_terms allowlist reviewed_assets")
    require(policy["schema_version"] == "clean-room-policy/v1")
    for key in ("deny_terms", "allowlist", "reviewed_assets"):
        require(type(policy[key]) is list and len(policy[key]) <= MAX_RULES)
    require(policy["deny_terms"])
    ids, terms = set(), set()
    for rule in policy["deny_terms"]:
        fields(rule, "id term classification")
        require(type(rule["id"]) is str and re.fullmatch(r"term-[0-9]{3}", rule["id"]))
        term = normalize(string(rule["term"], maximum=128))
        require(4 <= len(term) <= 128 and len(rule["term"].split()) <= 16)
        require(rule["classification"] in ("origin", "private", "tenant"))
        require(rule["id"] not in ids and term not in terms)
        ids.add(rule["id"])
        terms.add(term)
    seen = set()
    for entry in policy["allowlist"]:
        fields(entry, "rule_id path location context_sha256 justification")
        require(entry["rule_id"] in ids)
        relative_path(entry["path"])
        require(entry["location"] in ("content", "path"))
        sha(entry["context_sha256"])
        string(entry["justification"], minimum=8)
        key = (
            entry["rule_id"],
            entry["path"],
            entry["location"],
            entry["context_sha256"],
        )
        require(key not in seen)
        seen.add(key)
    assets = set()
    for entry in policy["reviewed_assets"]:
        fields(entry, "path sha256 authorship license metadata_scrubbed justification")
        relative_path(entry["path"])
        sha(entry["sha256"])
        for key in ("authorship", "license", "justification"):
            string(entry[key], minimum=3 if key == "license" else 8)
        require(entry["metadata_scrubbed"] is True and entry["path"] not in assets)
        assets.add(entry["path"])
    return policy
