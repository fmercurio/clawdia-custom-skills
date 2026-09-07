"""Strict, offline YAML boundary; never include source values in diagnostics."""
import math

import yaml


class SourceError(ValueError):
    """Invalid or ambiguous canonical metadata."""


class StrictLoader(yaml.SafeLoader):
    def compose_node(self, parent, index):
        event = self.peek_event()
        if isinstance(event, yaml.AliasEvent) or getattr(event, 'anchor', None):
            raise SourceError('YAML anchors and aliases are not allowed')
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key == '<<' or key in result:
                raise SourceError('YAML keys must be unique strings; merges are forbidden')
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def _finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise SourceError('nonfinite YAML number')
    if isinstance(value, dict):
        for child in value.values():
            _finite(child)
    elif isinstance(value, list):
        for child in value:
            _finite(child)


def load_source(path, *, require_capability_catalog=True):
    try:
        document = yaml.load(path.read_text(encoding='utf-8'), Loader=StrictLoader)
        _finite(document)
    except (yaml.YAMLError, UnicodeError, OSError, RecursionError) as exc:
        raise SourceError('cannot read unambiguous YAML registry') from exc
    if (not isinstance(document, dict) or 'skills' not in document
            or set(document) - {'skills', 'capability_catalog'}
            or (require_capability_catalog and 'capability_catalog' not in document)):
        raise SourceError('registry requires only skills and capability_catalog')
    source = document.get('capability_catalog')
    if 'capability_catalog' in document and (not isinstance(source, dict)
            or set(source) != {'schema_version', 'capabilities', 'artifacts', 'bundles'}
            or source['schema_version'] != 'clawdia-capability-source/v1'
            or any(not isinstance(source[key], list)
                   for key in ('capabilities', 'artifacts', 'bundles'))):
        raise SourceError('invalid capability_catalog envelope')
    if not isinstance(document['skills'], list) or not document['skills']:
        raise SourceError('registry requires legacy skills entries')
    for entry in document['skills']:
        if (not isinstance(entry, dict)
                or any(not isinstance(entry.get(key), str)
                       for key in ('name', 'status', 'category'))
                or ((require_capability_catalog or 'description' in entry)
                    and not isinstance(entry.get('description'), str))
                or not isinstance(entry.get('installation'), dict)
                or not isinstance(entry['installation'].get('repo_path'), str)
                or ('version' in entry and not isinstance(entry['version'], str))):
            raise SourceError('malformed legacy governed fields')
        for key in ('name', 'status', 'category', 'version'):
            if key in entry and entry[key] != entry[key].strip():
                raise SourceError('legacy identity and governance values must be exact')
        repo_path = entry['installation']['repo_path']
        if not repo_path or repo_path != repo_path.strip() or repo_path.startswith('/'):
            raise SourceError('legacy repo_path must be a canonical relative path')
    return document
