"""Conservative local marker heuristics, never a complete secret detector."""

import ipaddress
import json
import re
import unicodedata

PREFIX = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,}|"
    r"github_pat_[A-Za-z0-9_]{30,}|xoxb-[A-Za-z0-9-]{20,}|"
    r"AIza[A-Za-z0-9_-]{30,})"
)
PEM = re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----")
JWT = re.compile(
    r"(?<![\w-])eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."
    r"[A-Za-z0-9_-]{8,}(?![\w-])"
)
ASSIGN = re.compile(r"""(?ix)(?<!\w)["']?(?:password|passwd|token|api[\s_-]?key|access[_-]?token|secret)
    ["']?\s*[:=]\s*(?P<value>"[^"\r\n]*"|'[^'\r\n]*'|\{\{[^\r\n]*?\}\}|[^\s,;]+)""")
TEMPLATE = re.compile(r"(?:\$\{[A-Z][A-Z0-9_]*\}|\{\{\s*[A-Z][A-Z0-9_]*\s*\}\})")
HOME = re.compile(r"(?:/(?:Users|home)/[^/\s]+|[A-Za-z]:[\\/]Users[\\/][^\\/\s]+)")
IP = re.compile(
    r"(?<![\w.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![\w.])|"
    r"(?<![\w:])[0-9a-fA-F]*:[0-9a-fA-F:.%]+"
)
EXAMPLES = tuple(
    ipaddress.ip_network(s)
    for s in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "2001:db8::/32")
)

# Context recognition is deliberately smaller than the scanner's text budget.
JSON_CONTEXT_CHARS = 64 * 1024
JSON_CONTEXT_DEPTH = 32
JSON_TOKENS = re.compile(r'"(?:[^"\\]|\\.)*"|[{}\[\]]')


def json_property_spans(value):
    """Return exact key-to-string spans only after bounded, strict JSON validation."""
    if len(value) > JSON_CONTEXT_CHARS or not value.lstrip().startswith(("{", "[")):
        return set()
    tokens = list(JSON_TOKENS.finditer(value))
    depth = 0
    for token in tokens:
        if token[0] in ("{", "["):
            depth += 1
            if depth > JSON_CONTEXT_DEPTH:
                return set()
        elif token[0] in ("}", "]"):
            depth -= 1

    def unique_object(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = item
        return result

    def reject_constant(_):
        raise ValueError("non-JSON constant")

    try:
        json.loads(
            value, object_pairs_hook=unique_object, parse_constant=reject_constant
        )
    except (ValueError, RecursionError):
        return set()
    # In valid JSON, a string token followed by ':' is an actual property key.
    # Whole string tokens prevent matches inside values from borrowing context.
    return {
        (key.start(), item.end())
        for key, item in zip(tokens, tokens[1:])
        if key[0].startswith('"')
        and item[0].startswith('"')
        and value[key.end() : item.start()].strip() == ":"
    }


def markers(value):
    value = unicodedata.normalize("NFKC", value)
    json_spans = json_property_spans(value)
    json_like = value.lstrip().startswith(("{", "["))
    for rule, pattern in (
        ("builtin-001", PREFIX),
        ("builtin-002", PEM),
        ("builtin-003", JWT),
        ("builtin-005", HOME),
    ):
        for match in pattern.finditer(value):
            yield rule, value.count("\n", 0, match.start()) + 1
    for match in ASSIGN.finditer(value):
        literal = match["value"]
        if len(literal) >= 2 and literal[0] in "\"'" and literal[-1] == literal[0]:
            literal = literal[1:-1]
        line_start = (
            max(
                value.rfind("\n", 0, match.start()), value.rfind("\r", 0, match.start())
            )
            + 1
        )
        standalone = (
            not json_like
            and not value[line_start : match.start()].strip(" \t")
            and not any(q in value[match.start() : match.start("value")] for q in "\"'")
            and "\n" not in match[0]
            and "\r" not in match[0]
            and re.match(r"[ \t]*(?:\r?\n|\r|$)", value[match.end() :])
        )
        complete = standalone or (match.start(), match.end()) in json_spans
        if not complete or not TEMPLATE.fullmatch(literal):
            yield "builtin-004", value.count("\n", 0, match.start()) + 1
    for match in IP.finditer(value):
        try:
            address = ipaddress.ip_address(match[0].split("%")[0])
        except ValueError:
            continue
        if address.version == 6 and address.ipv4_mapped:
            address = address.ipv4_mapped
        if address.is_loopback or any(
            address in network
            for network in EXAMPLES
            if address.version == network.version
        ):
            continue
        if not address.is_global:
            yield "builtin-006", value.count("\n", 0, match.start()) + 1
