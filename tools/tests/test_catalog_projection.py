"""Offline projection pipeline tests using synthetic catalog metadata."""
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml
from test_generate_catalog import REPO_ROOT, run_generate, write_registry, write_skill


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        shutil.copytree(REPO_ROOT / 'schemas', self.root / 'schemas')
        write_registry(self.root, [dict(name='legacy', status='candidate',
                       category='testing', description='Synthetic legacy entry.',
                       repo_path='skills/testing/legacy')])
        write_skill(self.root, 'legacy', 'testing')
        self.path = self.root / 'registry/skills-registry.yaml'
        self.legacy = self.path.read_text().split('capability_catalog:')[0]
        self.source = {'schema_version': 'clawdia-capability-source/v1',
                       'capabilities': [], 'artifacts': [], 'bundles': []}
        self.save()

    def save(self):
        self.path.write_text(self.legacy + yaml.safe_dump(
            {'capability_catalog': self.source}, sort_keys=False), encoding='utf-8')

    def generate(self, *args):
        return run_generate(self.root, list(args))

    def test_package_imports_and_legacy_reader_compatibility(self):
        import os
        import subprocess
        import sys
        env = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH'}
        code = (
            'from pathlib import Path; '
            'from tools.generate_catalog import parse_registry_entries; '
            'from tools.catalog_projection import projection_schema; '
            'from tools.validate_capability_contract import validate_file; '
            f'entries, errors = parse_registry_entries(Path({str(self.path)!r})); '
            'assert not errors, errors; assert entries[0]["name"] == "legacy"'
        )
        # Inventory consumers accept legacy-only registries; generation does not.
        self.path.write_text(self.legacy, encoding='utf-8')
        result = subprocess.run([sys.executable, '-c', code], cwd=REPO_ROOT,
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        document = yaml.safe_load(self.path.read_text())
        del document['skills'][0]['description']
        self.path.write_text(yaml.safe_dump(document), encoding='utf-8')
        result = subprocess.run([sys.executable, '-c', code], cwd=REPO_ROOT,
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(self.generate().returncode, 0)
        self.assertFalse((self.root / 'dist').exists())

    def test_empty_cli_projection_and_checksums(self):
        result = self.generate()
        self.assertEqual(result.returncode, 0, result.stderr)
        for name, channel in [('catalog.v1.json', 'stable'),
                              ('catalog.preview.v1.json', 'preview')]:
            path = self.root / 'dist' / name
            self.assertTrue(path.exists(), 'CLI must emit machine projections')
            data = path.read_bytes()
            self.assertEqual(json.loads(data), dict(
                schema_version='clawdia-catalog-projection/v1', channel=channel,
                capabilities=[], artifacts=[], bundles=[], default_installable_artifacts=[]))
            self.assertEqual(path.with_suffix('.json.sha256').read_bytes(),
                             f'{hashlib.sha256(data).hexdigest()}  {name}\n'.encode())
            self.assertTrue(data.endswith(b'\n'))

    def test_strict_yaml_source_rejected_before_writes(self):
        valid = self.path.read_text()
        invalid = [valid + 'capability_catalog: null\n',
                   valid.replace('capability_catalog:', 'capability_catalog: &shared'),
                   valid + 'extra: *missing\n', valid + '<<: {}\n',
                   valid.replace('    status: candidate',
                                 '    status: candidate\n    status: approved'),
                   '!!python/object:unsafe {}', '[]',
                   valid + 'extra: .nan\n',
                   valid.replace('capabilities: []', 'capabilities: null'),
                   valid.replace('schema_version: clawdia-capability-source/v1',
                                 'schema_version: wrong'),
                   valid.replace('capabilities: []', 'unknown: []'),
                   valid.replace('capability_catalog:\n', 'capability_catalog: null\nignored:\n')]
        for text in invalid:
            with self.subTest(case=invalid.index(text)):
                self.path.write_text(text)
                result = self.generate()
                self.assertNotEqual(result.returncode, 0, 'ambiguous source must fail')
                self.assertFalse((self.root / 'CATALOG.md').exists())
                self.assertFalse((self.root / 'dist').exists())
        self.path.write_text(valid)
        # Standard YAML layout must have the same governed interpretation.
        doc = yaml.safe_load(valid)
        self.path.write_text(yaml.safe_dump(doc))
        result = self.generate()
        self.assertEqual(result.returncode, 0, result.stderr)

    def populate(self):
        fixture = REPO_ROOT / 'tools/tests/fixtures/capability_catalog/v1/projection-source.json'
        self.source = json.loads(fixture.read_bytes())
        return self.source['artifacts']

    def test_channels_statuses_delivery_and_public_schema(self):
        import copy
        from jsonschema import Draft202012Validator
        artifacts = self.populate()
        for status in ['draft', 'candidate', 'profile-overlay', 'deprecated', 'rejected']:
            item = copy.deepcopy(artifacts[-1])
            item.update(id='status-' + status, status=status)
            artifacts.append(item)
        candidate_cap = copy.deepcopy(self.source['capabilities'][0])
        candidate_cap['id'] = 'candidate-only'
        self.source['capabilities'].append(candidate_cap)
        next(a for a in artifacts if a['id'] == 'status-candidate')['provides'] = ['candidate-only']
        self.save()
        result = self.generate()
        self.assertEqual(result.returncode, 0, result.stderr)
        stable = json.loads((self.root / 'dist/catalog.v1.json').read_bytes())
        preview = json.loads((self.root / 'dist/catalog.preview.v1.json').read_bytes())
        self.assertEqual(len(stable['artifacts']), 6)
        self.assertEqual(len(preview['artifacts']), 7)
        self.assertEqual([c['id'] for c in stable['capabilities']], ['source-review'])
        self.assertEqual(len(preview['capabilities']), 2)
        self.assertEqual(set(stable['default_installable_artifacts']),
                         {a['id'] for a in artifacts if a['status'] == 'approved'
                          and a['delivery_mode'] == 'installable'})
        self.assertEqual(preview['default_installable_artifacts'],
                         stable['default_installable_artifacts'])
        schema_path = self.root / 'schemas/capability-catalog/v1/catalog-projection.schema.json'
        self.assertTrue(schema_path.exists())
        validator = Draft202012Validator(json.loads(schema_path.read_bytes()))
        validator.validate(stable)
        validator.validate(preview)
        self.assertFalse(validator.is_valid(dict(stable, installed=True)))
        stable['artifacts'][0]['tenant'] = 'forbidden'
        self.assertFalse(validator.is_valid(stable))
        self.assertIn('## Projeções v1', (self.root / 'CATALOG.md').read_text())

    def test_invalid_entities_including_excluded_fail_before_writes(self):
        import copy
        self.populate()
        baseline = copy.deepcopy(self.source)
        mutations = [lambda a: a.update(status='unknown'),
                     lambda a: a.update(delivery_mode='unknown'),
                     lambda a: a.update(version='01.0.0'),
                     lambda a: a.update(version='1.0.0\n'),
                     lambda a: a.update(requires_approval='false'),
                     lambda a: a.update(tenant='private'),
                     lambda a: a.update(label=None),
                     lambda a: a['runtime_compatibility'][0].update(
                         min_version='2.0.0', max_version_exclusive='1.0.0'),
                     lambda a: a['requires']['artifacts'].append(a['id'])]
        for index, mutate in enumerate(mutations):
            with self.subTest(case=index):
                self.source = copy.deepcopy(baseline)
                artifact = self.source['artifacts'][0]
                artifact['status'] = 'rejected'
                mutate(artifact)
                self.save()
                result = self.generate()
                self.assertNotEqual(result.returncode, 0, 'invalid entity must fail')
                self.assertNotIn('private', result.stderr)
                self.assertFalse((self.root / 'dist').exists())
        self.source = copy.deepcopy(baseline)
        artifact = self.source['artifacts'][0]
        artifact.update(id='legacy', status='approved', kind='skill', version='1.0.0')
        self.save()
        self.assertNotEqual(self.generate().returncode, 0, 'legacy approval disagreement')

    def test_canonical_relations_fail_closed_even_when_excluded(self):
        import copy
        self.populate()
        baseline = copy.deepcopy(self.source)
        def duplicate(source):
            artifact = copy.deepcopy(source['artifacts'][0])
            artifact['version'] = '2.0.0'
            source['artifacts'].append(artifact)
        def cycle(source):
            a, b = source['artifacts'][:2]
            a['requires']['artifacts'] = [b['id']]
            b['requires']['artifacts'] = [a['id']]
        mutations = [duplicate, cycle,
                     lambda s: s['artifacts'][0]['provides'].append('missing'),
                     lambda s: s['artifacts'][0]['requires']['artifacts'].append('missing'),
                     lambda s: s['artifacts'][0]['conflicts']['artifacts'].append('missing'),
                     lambda s: s['artifacts'][0]['requires']['capabilities'].append('missing'),
                     lambda s: s['artifacts'][0]['conflicts']['capabilities'].append('missing'),
                     lambda s: s['bundles'][0]['requires']['bundles'].append('missing'),
                     lambda s: s['bundles'][0]['conflicts']['bundles'].append('missing'),
                     lambda s: s['bundles'][0]['artifacts'][0].update(version='2.0.0'),
                     lambda s: s['bundles'][0]['artifacts'][0].update(artifact_id='missing')]
        for index, mutate in enumerate(mutations):
            with self.subTest(case=index):
                self.source = copy.deepcopy(baseline)
                for key in ('artifacts', 'bundles'):
                    for item in self.source[key]:
                        item['status'] = 'rejected'
                mutate(self.source)
                self.save()
                result = self.generate()
                self.assertNotEqual(result.returncode, 0, 'canonical relations must fail')
                self.assertFalse((self.root / 'dist').exists())

    def test_channel_closure_and_transitive_eligibility(self):
        import copy
        artifacts = self.populate()
        baseline = copy.deepcopy(self.source)
        skill = next(a for a in artifacts if a['id'] == 'source-review-skill')
        skill['status'] = 'candidate'
        self.save()
        self.assertNotEqual(self.generate().returncode, 0,
                            'approved package and bundle must not pull candidate skill')
        self.assertFalse((self.root / 'dist').exists())
        # Optional members must also resolve in the channel.
        self.source = copy.deepcopy(baseline)
        self.source['bundles'][0]['artifacts'][0]['required'] = False
        next(a for a in self.source['artifacts'] if a['id'] == 'source-review-skill')['status'] = 'draft'
        self.source['artifacts'] = [a for a in self.source['artifacts']
                                    if a['kind'] != 'package']
        self.save()
        self.assertNotEqual(self.generate().returncode, 0)
        self.source = copy.deepcopy(baseline)
        skill = next(a for a in self.source['artifacts'] if a['id'] == 'source-review-skill')
        skill['delivery_mode'] = 'reference'
        self.save()
        result = self.generate()
        self.assertEqual(result.returncode, 0, result.stderr)
        stable = json.loads((self.root / 'dist/catalog.v1.json').read_bytes())
        self.assertNotIn('research-foundation-package', stable['default_installable_artifacts'])
        self.assertNotIn('source-review-skill', stable['default_installable_artifacts'])

    def snapshot(self):
        paths = [self.root / 'CATALOG.md',
                 self.root / 'schemas/capability-catalog/v1/catalog-projection.schema.json']
        paths += sorted((self.root / 'dist').glob('*'))
        return {str(p.relative_to(self.root)): p.read_bytes() for p in paths if p.exists()}

    def test_repeat_reordered_input_and_derived_schema_determinism(self):
        import copy
        self.populate()
        cap = copy.deepcopy(self.source['capabilities'][0])
        cap['id'] = 'additional-capability'
        self.source['capabilities'].append(cap)
        self.source['artifacts'][0]['provides'].append(cap['id'])
        self.save()
        self.assertEqual(self.generate().returncode, 0)
        first = self.snapshot()
        self.assertEqual(self.generate().returncode, 0)
        self.assertEqual(first, self.snapshot())
        def reverse(value):
            if isinstance(value, dict):
                return {k: reverse(v) for k, v in reversed(list(value.items()))}
            if isinstance(value, list):
                return [reverse(v) for v in reversed(value)]
            return value
        self.source = reverse(self.source)
        self.save()
        self.assertEqual(self.generate().returncode, 0)
        self.assertEqual(first, self.snapshot(), 'equivalent reordered metadata must be byte-identical')
        schema = self.root / 'schemas/capability-catalog/v1/capability.schema.json'
        original = json.loads(schema.read_bytes())
        original['properties']['label']['maxLength'] = 119
        schema.write_text(json.dumps(original))
        self.assertNotEqual(self.generate('--check').returncode, 0)
        self.assertEqual(first, self.snapshot(), '--check must not repair derived schema')
        self.assertEqual(self.generate().returncode, 0)
        self.assertNotEqual(first['schemas/capability-catalog/v1/catalog-projection.schema.json'],
                            self.snapshot()['schemas/capability-catalog/v1/catalog-projection.schema.json'])

    def test_output_targets_reject_symlinks_and_source_collisions(self):
        target = self.root / 'untouched.md'
        target.write_text('source must survive\n')
        output = self.root / 'CATALOG.md'
        output.symlink_to(target)
        before = target.read_bytes()
        self.assertNotEqual(self.generate().returncode, 0, 'symlink output must fail')
        self.assertEqual(target.read_bytes(), before)
        self.assertFalse((self.root / 'dist').exists())
        output.unlink()
        for path in [self.path, self.root / 'tools/generate_catalog.py',
                     self.root / 'schemas/capability-catalog/v1/artifact.schema.json',
                     self.root / 'dist/catalog.v1.json', target]:
            with self.subTest(path=path.name):
                self.assertNotEqual(self.generate('--output', str(path)).returncode, 0)
                self.assertFalse((self.root / 'dist').exists())
        outside = self.root / 'outside'
        outside.mkdir()
        (self.root / 'dist').symlink_to(outside, target_is_directory=True)
        self.assertNotEqual(self.generate().returncode, 0)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse(output.exists())

    def test_projection_cli_validates_semantics(self):
        import copy
        import subprocess
        import sys
        self.populate()
        self.save()
        self.assertEqual(self.generate().returncode, 0)
        document_path = self.root / 'dist/catalog.v1.json'
        def validate():
            return subprocess.run([sys.executable,
                str(REPO_ROOT / 'tools/validate_capability_contract.py'),
                '--schemas-dir', str(self.root / 'schemas/capability-catalog/v1'),
                '--schema', 'projection', str(document_path)], capture_output=True, text=True)
        self.assertEqual(validate().returncode, 0, 'projection CLI must support semantic validation')
        baseline = json.loads(document_path.read_bytes())
        mutations = [lambda d: d['artifacts'][0].update(status='candidate'),
                     lambda d: d['default_installable_artifacts'].append('missing'),
                     lambda d: d['artifacts'][0]['requires']['artifacts'].append('missing'),
                     lambda d: d['artifacts'][0]['runtime_compatibility'][0].update(
                         min_version='3.0.0', max_version_exclusive='2.0.0')]
        for mutate in mutations:
            doc = copy.deepcopy(baseline)
            mutate(doc)
            document_path.write_text(json.dumps(doc))
            self.assertNotEqual(validate().returncode, 0)

    def test_check_compares_all_raw_bytes_without_repairs(self):
        self.populate()
        self.save()
        self.assertEqual(self.generate().returncode, 0)
        original = self.snapshot()
        self.assertEqual(self.generate('--check').returncode, 0)
        for name, data in original.items():
            path = self.root / name
            for changed in (None, data.replace(b'\n', b'\r\n'), data + b'drift\n'):
                with self.subTest(output=name, missing=changed is None):
                    if changed is None:
                        path.unlink()
                    else:
                        path.write_bytes(changed)
                    before = self.snapshot()
                    self.assertNotEqual(self.generate('--check').returncode, 0)
                    self.assertEqual(before, self.snapshot())
                    path.write_bytes(data)
        self.source['artifacts'][0]['status'] = 'unknown'
        self.save()
        self.assertNotEqual(self.generate().returncode, 0)
        self.assertEqual(original, self.snapshot(), 'input failure must preserve every old output')

    def test_capability_dependency_gating_and_excluded_conflicts(self):
        import copy
        artifacts = self.populate()
        cap = copy.deepcopy(self.source['capabilities'][0])
        cap['id'] = 'dependency-capability'
        self.source['capabilities'].append(cap)
        provider = copy.deepcopy(artifacts[0])
        provider.update(id='dependency-provider', status='candidate', provides=[cap['id']],
                        kind='tool', delivery_mode='installable')
        provider['requires'] = dict(capabilities=[], artifacts=[], runtime_features=[])
        artifacts.append(provider)
        consumer = next(a for a in artifacts if a['id'] == 'source-review-skill')
        consumer['requires']['capabilities'] = [cap['id']]
        self.save()
        self.assertNotEqual(self.generate().returncode, 0, 'stable capability lacks provider')
        self.assertFalse((self.root / 'dist').exists())
        provider.update(status='approved', delivery_mode='reference')
        self.save()
        self.assertEqual(self.generate().returncode, 0)
        stable = json.loads((self.root / 'dist/catalog.v1.json').read_bytes())
        self.assertNotIn(consumer['id'], stable['default_installable_artifacts'])
        self.assertNotIn('research-foundation-package', stable['default_installable_artifacts'])
        consumer['requires']['capabilities'] = []
        provider['status'] = 'rejected'
        consumer['conflicts']['artifacts'] = [provider['id']]
        self.save()
        self.assertEqual(self.generate().returncode, 0)
        stable = json.loads((self.root / 'dist/catalog.v1.json').read_bytes())
        self.assertNotIn(provider['id'], [a['id'] for a in stable['artifacts']])
        self.assertNotIn(cap['id'], [c['id'] for c in stable['capabilities']])
        projected_consumer = next(a for a in stable['artifacts'] if a['id'] == consumer['id'])
        self.assertEqual(projected_consumer['conflicts']['artifacts'], [provider['id']])

    def test_legacy_agreement_and_no_legacy_private_fields_serialized(self):
        import copy
        artifacts = self.populate()
        migrated = copy.deepcopy(artifacts[0])
        migrated.update(id='legacy', kind='skill', version='1.0.0', status='candidate')
        artifacts.append(migrated)
        self.legacy = self.legacy.replace('    status:', '    version: 1.0.0\n    status:')
        self.legacy += '# This source comment is never projected.\n'
        self.save()
        self.assertEqual(self.generate().returncode, 0)
        preview_bytes = (self.root / 'dist/catalog.preview.v1.json').read_bytes()
        self.assertNotIn(b'This source comment', preview_bytes)
        self.assertNotIn(b'install_date', preview_bytes)
        for key, value in [('version', '2.0.0'), ('kind', 'tool'), ('status', 'approved')]:
            before = migrated[key]
            migrated[key] = value
            self.save()
            self.assertNotEqual(self.generate().returncode, 0)
            self.assertEqual(preview_bytes, (self.root / 'dist/catalog.preview.v1.json').read_bytes())
            migrated[key] = before

    def test_legacy_identity_whitespace_cannot_bypass_status_agreement(self):
        import copy
        artifacts = self.populate()
        migrated = copy.deepcopy(artifacts[0])
        migrated.update(id='legacy', kind='skill', version='1.0.0', status='approved')
        artifacts.append(migrated)
        self.legacy = self.legacy.replace('    status:', '    version: 1.0.0\n    status:')
        original = self.legacy
        self.save()
        self.assertNotEqual(self.generate().returncode, 0, 'candidate legacy cannot become approved')
        for name in [' legacy', 'legacy ', 'legacy\t', 'legacy\n']:
            with self.subTest(name=repr(name)):
                self.legacy = original.replace('name: legacy', 'name: ' + json.dumps(name))
                self.save()
                result = self.generate()
                self.assertNotEqual(result.returncode, 0,
                                    'identity normalization must not bypass canonical governance')
                self.assertFalse((self.root / 'dist').exists())

    def test_legacy_path_alias_cannot_bypass_kind_agreement(self):
        import copy
        artifacts = self.populate()
        migrated = copy.deepcopy(artifacts[0])
        migrated.update(id='legacy', kind='skill', version='1.0.0', status='approved')
        artifacts.append(migrated)
        self.legacy = self.legacy.replace('status: candidate', 'status: approved')
        self.legacy = self.legacy.replace('    status:', '    version: 1.0.0\n    status:')
        self.save()
        valid = self.generate()
        self.assertEqual(valid.returncode, 0, valid.stderr)
        before = self.snapshot()
        migrated['kind'] = 'package'
        self.save()
        self.assertNotEqual(self.generate().returncode, 0, 'skill cannot become package')
        original = self.legacy
        base_path = 'skills/testing/legacy'
        for path in [' ' + base_path, '\t' + base_path, '/' + base_path,
                     base_path + ' ', base_path + '\n']:
            with self.subTest(path=repr(path)):
                self.legacy = original
                migrated['kind'] = 'skill'
                self.save()
                self.assertEqual(self.generate().returncode, 0)
                migrated['kind'] = 'package'
                legacy_document = yaml.safe_load(original)
                legacy_document['skills'][0]['installation']['repo_path'] = path
                self.legacy = yaml.safe_dump(legacy_document, sort_keys=False)
                self.save()
                result = self.generate()
                self.assertNotEqual(result.returncode, 0)
                from tools.catalog_source import SourceError, load_source
                with self.assertRaisesRegex(SourceError, 'legacy repo_path must be a canonical relative path'):
                    load_source(self.path)
                self.assertNotIn('Traceback', result.stderr)
                self.assertEqual(self.snapshot(), before)

        # Preserve the legacy registry's harmless trailing directory slash.
        migrated['kind'] = 'skill'
        legacy_document = yaml.safe_load(original)
        legacy_document['skills'][0]['installation']['repo_path'] = base_path + '/'
        self.legacy = yaml.safe_dump(legacy_document, sort_keys=False)
        self.save()
        self.assertEqual(self.generate().returncode, 0)
        self.assertEqual(self.snapshot(), before)

    def test_markdown_override_keeps_dist_at_root_and_checksums_verify(self):
        import subprocess
        self.populate()
        self.save()
        output = self.root / 'review/catalog.md'
        result = self.generate('--output', str(output))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(output.exists())
        self.assertFalse((self.root / 'CATALOG.md').exists())
        self.assertTrue((self.root / 'dist/catalog.v1.json').exists())
        self.assertEqual(self.generate('--output', str(output), '--check').returncode, 0)
        command = shutil.which('sha256sum') or shutil.which('shasum')
        if command is None:
            self.skipTest('system checksum checker unavailable; exact hashlib verification covered')
        result = subprocess.run([command, '-c', 'catalog.v1.json.sha256',
                                 'catalog.preview.v1.json.sha256'],
                                cwd=self.root / 'dist', capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_diagnostics_do_not_echo_source_values(self):
        marker = 'synthetic-sensitive-value'
        self.path.write_text(self.path.read_text().replace('status: candidate',
                                                          'status: ' + marker))
        result = self.generate()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(marker, result.stderr)
        self.save()
        schema_path = self.root / 'schemas/capability-catalog/v1/artifact.schema.json'
        schema = json.loads(schema_path.read_bytes())
        schema['$ref'] = 'https://invalid.example/' + marker
        schema_path.write_text(json.dumps(schema))
        result = self.generate()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(marker, result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        self.assertFalse((self.root / 'dist').exists())

    def test_non_directory_output_ancestor_fails_before_markdown_write(self):
        (self.root / 'dist').write_bytes(b'Existing source file\n')
        result = self.generate()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / 'CATALOG.md').exists(),
                         'all static output path failures must precede writes')
        self.assertEqual((self.root / 'dist').read_bytes(), b'Existing source file\n')

    def test_bundle_statuses_duplicate_ids_and_bundle_cycles(self):
        import copy
        self.populate()
        baseline = copy.deepcopy(self.source['bundles'][0])
        for status in ['candidate', 'draft', 'deprecated', 'rejected']:
            bundle = copy.deepcopy(baseline)
            bundle.update(id='bundle-' + status, status=status)
            self.source['bundles'].append(bundle)
        self.save()
        self.assertEqual(self.generate().returncode, 0)
        for channel, name, count in [('stable', 'catalog.v1.json', 1),
                                     ('preview', 'catalog.preview.v1.json', 2)]:
            projected = json.loads((self.root / 'dist' / name).read_bytes())
            self.assertEqual(projected['channel'], channel)
            self.assertEqual(len(projected['bundles']), count)
        snapshot = self.snapshot()
        for key in ('capabilities', 'artifacts', 'bundles'):
            duplicate = copy.deepcopy(self.source[key][0])
            self.source[key].append(duplicate)
            self.save()
            self.assertNotEqual(self.generate().returncode, 0)
            self.assertEqual(snapshot, self.snapshot())
            self.source[key].pop()
        a, b = self.source['bundles'][-2:]
        a['requires']['bundles'] = [b['id']]
        b['requires']['bundles'] = [a['id']]
        self.save()
        self.assertNotEqual(self.generate().returncode, 0)
        self.assertEqual(snapshot, self.snapshot())

    def test_hardlink_output_alias_and_root_escape(self):
        import os
        target = self.root / 'source.md'
        target.write_bytes(b'Preserve source\n')
        output = self.root / 'CATALOG.md'
        os.link(target, output)
        self.assertNotEqual(self.generate().returncode, 0)
        self.assertEqual(target.read_bytes(), b'Preserve source\n')
        self.assertFalse((self.root / 'dist').exists())
        output.unlink()
        outside = self.root / '..' / (self.root.name + '-escape.md')
        self.assertNotEqual(self.generate('--output', str(outside)).returncode, 0)
        self.assertFalse(outside.exists())
        self.assertFalse(output.exists())
