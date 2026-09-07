"""Deterministic public projections of the canonical capability metadata."""
import hashlib
import json
from pathlib import Path

if __package__:
    from .catalog_source import SourceError
    from .validate_capability_contract import (
        load_json, validate_document, validate_artifact_relations, validate_bundle_relations,
    )
else:
    from catalog_source import SourceError
    from validate_capability_contract import (
        load_json, validate_document, validate_artifact_relations, validate_bundle_relations,
    )


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + '\n').encode('utf-8')


ENTITY_TYPES = {'capabilities': 'capability', 'artifacts': 'artifact', 'bundles': 'bundle'}


def projection_schema(schema_dir):
    definitions = {}
    for name in ENTITY_TYPES.values():
        schema = json.loads((schema_dir / f'{name}.schema.json').read_bytes())
        def localize(value):
            if isinstance(value, dict):
                return {key: (f'#/$defs/{name}' + child[1:]
                              if key in {'$ref', '$dynamicRef'} and child.startswith('#')
                              else localize(child))
                        for key, child in value.items() if key not in {'$id', '$schema'}}
            if isinstance(value, list):
                return [localize(child) for child in value]
            return value
        definitions[name] = localize(schema)
    properties = {
        'schema_version': {'const': 'clawdia-catalog-projection/v1'},
        'channel': {'enum': ['stable', 'preview']},
        **{key: {'type': 'array', 'items': {'$ref': f'#/$defs/{name}'}}
           for key, name in ENTITY_TYPES.items()},
        'default_installable_artifacts': {
            'type': 'array', 'uniqueItems': True,
            'items': definitions['artifact']['properties']['id']},
    }
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema',
            '$id': 'urn:clawdia:capability-catalog:v1:projection',
            'type': 'object', 'additionalProperties': False,
            'required': list(properties), 'properties': properties, '$defs': definitions,
            'allOf': [{
                'if': {'properties': {'channel': {'const': channel}}},
                'then': {'properties': {
                    key: {'items': {'properties': {'status': {'enum': statuses}}}}
                    for key in ('artifacts', 'bundles')}}}
                for channel, statuses in [('stable', ['approved']),
                                          ('preview', ['approved', 'candidate'])]]}


def canonical_order(value):
    """All v1 entity arrays are sets; sort records by identity, then full content."""
    if isinstance(value, dict):
        return {key: canonical_order(child) for key, child in value.items()}
    if isinstance(value, list):
        ordered = [canonical_order(child) for child in value]
        return sorted(ordered, key=lambda child: (
            child.get('id', child.get('artifact_id', child.get('runtime', '')))
            if isinstance(child, dict) else str(child), json_bytes(child)))
    return value


def project(source, channel):
    statuses = {'approved'} if channel == 'stable' else {'approved', 'candidate'}
    records = {key: sorted((item for item in source[key] if item['status'] in statuses),
                           key=lambda item: item['id']) for key in ('artifacts', 'bundles')}
    used = set()
    for item in records['artifacts'] + records['bundles']:
        used.update(item.get('provides', item.get('capabilities', [])))
        used.update(item['requires']['capabilities'])
        used.update(item['conflicts']['capabilities'])
    result = dict(schema_version='clawdia-catalog-projection/v1', channel=channel,
                  capabilities=sorted((c for c in source['capabilities'] if c['id'] in used),
                                      key=lambda item: item['id']), **records,
                  default_installable_artifacts=eligible_artifacts(source))
    validate_relations(result, canonical=False)
    return canonical_order(result)


def eligible_artifacts(source):
    artifacts = {a['id']: a for a in source['artifacts']}
    eligible = {a['id'] for a in artifacts.values()
                if a['status'] == 'approved' and a['delivery_mode'] == 'installable'
                and a['kind'] != 'framework'}
    providers = {}
    for artifact in artifacts.values():
        for capability in artifact['provides']:
            providers.setdefault(capability, set()).add(artifact['id'])
    while True:
        retained = {key for key in eligible
                    if set(artifacts[key]['requires']['artifacts']) <= eligible
                    and all(providers.get(cap) and providers[cap] <= eligible
                            for cap in artifacts[key]['requires']['capabilities'])}
        if retained == eligible:
            return sorted(eligible)
        eligible = retained


def validate_source_entities(source, legacy, schema_dir):
    for key, name in ENTITY_TYPES.items():
        schema = load_json(schema_dir / f'{name}.schema.json')
        for item in source[key]:
            if validate_document(item, schema, f'{name}.schema.json'):
                raise SourceError(f'invalid {name} contract')
    validate_relations(source)
    legacy_by_id = {entry['name']: entry for entry in legacy}
    for artifact in source['artifacts']:
        entry = legacy_by_id.get(artifact['id'])
        if entry is not None:
            kind = 'skill' if entry['installation']['repo_path'].startswith('skills/') else 'package'
            if (artifact['status'] != entry['status'] or artifact['version'] != entry.get('version')
                    or artifact['kind'] != kind):
                raise SourceError('artifact disagrees with legacy status, version or kind')


def validate_relations(source, *, canonical=True):
    indexes = {}
    all_ids = set()
    for key in ENTITY_TYPES:
        indexes[key] = {item['id']: item for item in source[key]}
        if len(indexes[key]) != len(source[key]) or all_ids.intersection(indexes[key]):
            raise SourceError('duplicate or ambiguous entity ID')
        all_ids.update(indexes[key])
    graph = {item['id']: set() for key in ('artifacts', 'bundles') for item in source[key]}
    providers = {}
    for artifact in source['artifacts']:
        for capability in artifact['provides']:
            providers.setdefault(capability, set()).add(artifact['id'])
    for key in ('artifacts', 'bundles'):
        for item in source[key]:
            declared = item.get('provides', item.get('capabilities', []))
            if not set(declared) <= indexes['capabilities'].keys():
                raise SourceError('unknown declared capability')
            for relation in ('requires', 'conflicts'):
                for target, ids in item[relation].items():
                    if target == 'runtime_features':
                        continue
                    # Published conflicts can identify canonically known excluded entities.
                    if not canonical and relation == 'conflicts' and target != 'capabilities':
                        continue
                    if not set(ids) <= indexes[target].keys():
                        raise SourceError('unknown relation reference')
                    if relation == 'requires':
                        if target == 'capabilities':
                            for capability in ids:
                                if not providers.get(capability):
                                    raise SourceError('required capability has no artifact provider')
                                graph[item['id']].update(providers[capability])
                        else:
                            graph[item['id']].update(ids)
            if key == 'bundles':
                for member in item['artifacts']:
                    artifact = indexes['artifacts'].get(member['artifact_id'])
                    if artifact is None or member['version'] != artifact['version']:
                        raise SourceError('unknown bundle member or mismatched artifact pin')
                    graph[item['id']].add(member['artifact_id'])
    # Every possible provider edge participates: conservative, no resolver selection.
    pending = dict(graph)
    while pending:
        ready = {key for key, deps in pending.items() if not deps.intersection(pending)}
        if not ready:
            raise SourceError('dependency cycle')
        for key in ready:
            del pending[key]
    return indexes


def validate_projection(document):
    """Semantic checks after schema validation, without installation or runtime solving."""
    try:
        validate_relations(document, canonical=False)
        allowed = set(eligible_artifacts(document))
        if not set(document['default_installable_artifacts']) <= allowed:
            raise SourceError('ineligible default artifact')
        for key, name in ENTITY_TYPES.items():
            for item in document[key]:
                if name == 'artifact' and validate_artifact_relations(Path('<memory>'), item):
                    raise SourceError('invalid artifact relations')
                if name == 'bundle' and validate_bundle_relations(Path('<memory>'), item):
                    raise SourceError('invalid bundle relations')
        # Preview must not hide an unsafe stable closure.
        project(document, 'stable')
    except (SourceError, RecursionError):
        return ['invalid projection relations or eligibility']
    return []


def projection_outputs(root, source):
    schema_dir = root / 'schemas/capability-catalog/v1'
    schema = projection_schema(schema_dir)
    outputs = {schema_dir / 'catalog-projection.schema.json': json_bytes(schema)}
    for channel, name in [('stable', 'catalog.v1.json'),
                          ('preview', 'catalog.preview.v1.json')]:
        projection = project(source, channel)
        if validate_document(projection, schema, 'catalog-projection.schema.json'):
            raise SourceError('invalid generated projection')
        data = json_bytes(projection)
        path = root / 'dist' / name
        outputs[path] = data
        outputs[path.with_suffix('.json.sha256')] = (
            f'{hashlib.sha256(data).hexdigest()}  {name}\n'.encode('ascii'))
    return outputs


def human_sections(source):
    lines = ['', '## Projeções v1', '',
             '> Cobertura parcial: somente capability_catalog alimenta as projeções. '
             'A migração dos metadados legados pertence à issue #46.', '',
             'Elegibilidade no catálogo não concede permissão de instalação.', '']
    for channel in ('stable', 'preview'):
        projection = project(source, channel)
        lines += [f'### {channel}', '']
        for key in ENTITY_TYPES:
            lines += [f'#### {key}', '']
            lines += [f"- `{item['id']}`" for item in projection[key]] or ['Nenhum registro.']
            lines.append('')
    return '\n'.join(lines)
