"""Synthetic-only public scanner contract tests. No imported source material."""

import json
import tempfile
import unittest
from pathlib import Path

from tools.scan_catalog import scan


class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "tree"
        self.root.mkdir()
        self.policy = self.base / "policy.json"
        self.document = dict(
            schema_version="clean-room-policy/v1",
            deny_terms=[
                dict(id="term-001", term="Synthetic Quartz", classification="origin")
            ],
            allowlist=[],
            reviewed_assets=[],
        )
        self.save()

    def save(self):
        self.policy.write_text(json.dumps(self.document), encoding="utf-8")

    def run_scan(self, *archives):
        return scan(self.root, self.policy, archives)

    def test_neutral_source_tracer(self):
        (self.root / "note.md").write_text("Neutral example.\n", encoding="utf-8")
        code, report = self.run_scan()
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["scanned_entries"], 1)
        self.assertEqual(report["unauthorized_findings"], 0)
        self.assertEqual(report["authorized_findings"], 0)

    def test_normalized_names_text_and_redaction(self):
        folder = self.root / ".hidden"
        folder.mkdir()
        (folder / "SÝNTHETIC_quartz.md").write_text(
            "# Ｓynthetic-\nQUÁRTZ\n", encoding="utf-8"
        )
        code, report = self.run_scan()
        self.assertEqual(code, 1)
        self.assertEqual(report["unauthorized_findings"], 2)
        self.assertEqual(
            {f["location"] for f in report["findings"]}, {"path", "content"}
        )
        output = json.dumps(report).lower()
        for sensitive in ("synthetic", "quartz", ".hidden", str(self.root)):
            self.assertNotIn(sensitive, output)
        self.assertTrue(all(len(f["path_id"]) == 64 for f in report["findings"]))

    def test_strict_policy_and_external_boundary(self):
        valid = self.policy.read_text()
        invalid = [
            "{}",
            "[]",
            "null",
            valid[:-1] + ',"extra":0}',
            valid.replace('"allowlist": []', '"allowlist": [], "allowlist": []'),
            valid.replace('"reviewed_assets": []', '"reviewed_assets": NaN'),
            valid.replace("term-001", "sensitive-invalid-id"),
            valid.replace("Synthetic Quartz", "\\ud800"),
        ]
        for data in invalid:
            with self.subTest(index=invalid.index(data)):
                self.policy.write_text(data)
                code, report = self.run_scan()
                self.assertEqual(code, 2)
                self.assertEqual(report["error"], "invalid_input")
                self.assertNotIn("sensitive", json.dumps(report))
        self.save()
        self.document["deny_terms"] = []
        self.save()
        self.assertEqual(self.run_scan()[0], 2)
        self.policy.unlink()
        self.assertEqual(self.run_scan()[0], 2)
        self.policy = self.root / "policy.json"
        self.document["deny_terms"] = [
            dict(id="term-001", term="Synthetic Quartz", classification="origin")
        ]
        self.save()
        self.assertEqual(self.run_scan()[0], 2)

    def test_allowlist_binds_term_path_and_full_matching_context(self):
        from tools.clean_room_policy import context_digest

        text = "prefix Synthetic\nQuartz suffix"
        target = self.root / "note.md"
        target.write_text(text)
        self.document["allowlist"] = [
            dict(
                rule_id="term-001",
                path="note.md",
                location="content",
                context_sha256=context_digest(text, "Synthetic Quartz"),
                justification="Synthetic test authorization",
            )
        ]
        self.save()
        code, report = self.run_scan()
        self.assertEqual(code, 0)
        self.assertEqual(report["authorized_findings"], 1)
        target.write_text(text + " changed")
        self.assertEqual(self.run_scan()[0], 1)
        target.write_text(text)
        target.rename(self.root / "elsewhere.md")
        self.assertEqual(self.run_scan()[0], 1)
        (self.root / "elsewhere.md").rename(target)
        self.document["deny_terms"][0]["term"] = "Other Pebble"
        target.write_text("Other Pebble")
        self.save()
        self.assertEqual(self.run_scan()[0], 1)
        self.document["allowlist"][0]["path"] = "*.md"
        self.save()
        self.assertEqual(self.run_scan()[0], 2)
        self.document["allowlist"][0]["path"] = "note.md"
        self.document["allowlist"].append(dict(self.document["allowlist"][0]))
        self.save()
        self.assertEqual(self.run_scan()[0], 2)

    def test_credentials_private_markers_and_inert_templates(self):
        samples = [
            prefix + "A" * length
            for prefix, length in [
                ("s" + "k-", 24),
                ("gh" + "p_", 36),
                ("github" + "_pat_", 40),
                ("xo" + "xb-", 32),
                ("AI" + "za", 35),
            ]
        ]
        samples += [
            "-----BEGIN " + "PRIVATE KEY-----",
            ".".join(["ey" + "J" + "a" * 15, "b" * 20, "c" * 24]),
            "pass" + 'word = "neutral-value"',
            "API" + "_KEY: neutral-value",
            "to" + "ken=abcd",
            "/" + "Users/" + "example-private/file",
            "/" + "home/" + "example-private/file",
            "https://" + "10." + "2.3.4/data",
            "http://[" + "fd12" + "::1]/",
        ]
        target = self.root / ".env"
        for index, value in enumerate(samples):
            with self.subTest(index=index):
                target.write_text(value)
                code, report = self.run_scan()
                self.assertEqual(code, 1)
                self.assertNotIn(value, json.dumps(report))
                self.assertTrue(
                    any(f["rule_id"].startswith("builtin-") for f in report["findings"])
                )
        target.write_text(
            "to" + "ken=${EXAMPLE_VALUE}\n" + "pass" + "word={{ EXAMPLE_VALUE }}"
        )
        self.assertEqual(self.run_scan()[0], 0)
        target.write_text("http://127.0.0.1 http://192.0.2.1 http://[2001:db8::1]")
        self.assertEqual(self.run_scan()[0], 0)

    def test_template_exemption_rejects_quotes_anywhere_in_key(self):
        target = self.root / "note.md"
        keys = [
            "password",
            "passwd",
            "token",
            "api key",
            "api_key",
            "api-key",
            "access_token",
            "access-token",
            "secret",
        ]
        templates = ["${EXAMPLE_VALUE}", "{{ EXAMPLE_VALUE }}"]
        for key in keys:
            for template in templates:
                for value_quote in ("", '"', "'"):
                    rhs = value_quote + template + value_quote
                    target.write_text(key + "=" + rhs)
                    self.assertEqual(self.run_scan()[0], 0)
                    for left, right in (
                        ("", '"'),
                        ("", "'"),
                        ('"', ""),
                        ("'", ""),
                        ('"', '"'),
                        ("'", "'"),
                        ('"', "'"),
                        ("'", '"'),
                    ):
                        with self.subTest(
                            key=key,
                            left=left,
                            right=right,
                            value_quote=value_quote,
                            template=template,
                        ):
                            target.write_text(left + key + right + "=" + rhs)
                            code, report = self.run_scan()
                            self.assertEqual(code, 1)
                            self.assertTrue(
                                any(
                                    f["rule_id"] == "builtin-004"
                                    for f in report["findings"]
                                )
                            )
                target.write_text(json.dumps({key: template}))
                self.assertEqual(self.run_scan()[0], 0)

    def test_template_exemption_requires_complete_paired_rhs(self):
        target = self.root / "note.md"
        key = "to" + "ken"
        for template in ("${EXAMPLE_VALUE}", "{{ EXAMPLE_VALUE }}"):
            for quote in ("", "'", '"'):
                exact = quote + template + quote
                cases = [(exact, 0), (exact + "suffix", 1), (exact + " suffix", 1)]
                if quote:
                    cases.append((quote + template, 1))
                    cases.append((quote + template + "suffix", 1))
                for rhs, expected in cases:
                    with self.subTest(template=template, quote=quote, rhs=rhs):
                        target.write_text(key + "=" + rhs)
                        code, report = self.run_scan()
                        self.assertEqual(code, expected)
                        if expected:
                            self.assertIn(
                                "builtin-004",
                                [f["rule_id"] for f in report["findings"]],
                            )
                target.write_text(json.dumps({key: template, "note": "neutral"}))
                self.assertEqual(self.run_scan()[0], 0)

    def test_template_context_suffix_matrix(self):
        target = self.root / "example.sh"
        key = "to" + "ken"
        for template in ("${EXAMPLE_VALUE}", "{{ EXAMPLE_VALUE }}"):
            for quote in ("", "'", '"'):
                for suffix in (
                    "}suffix",
                    "]suffix",
                    ",suffix",
                    "}",
                    "]",
                    ",",
                    " suffix",
                    "suffix",
                ):
                    for paired in (True, False) if quote else (True,):
                        rhs = quote + template + (quote if paired else "") + suffix
                        for embedded in (False, True):
                            text = key + "=" + rhs
                            if embedded:
                                text = json.dumps({"command": text, key: template})
                            with self.subTest(
                                template=template,
                                quote=quote,
                                suffix=suffix,
                                paired=paired,
                                embedded=embedded,
                            ):
                                target.write_text(text)
                                code, report = self.run_scan()
                                self.assertEqual(code, 1)
                                self.assertIn(
                                    "builtin-004",
                                    [f["rule_id"] for f in report["findings"]],
                                )

    def test_template_supported_context_controls(self):
        target = self.root / "note.md"
        key = "to" + "ken"
        for template in ("${EXAMPLE_VALUE}", "{{ EXAMPLE_VALUE }}"):
            cases = [quote + template + quote for quote in ("", "'", '"')]
            texts = ["  " + key + "=" + rhs + " \t\r\n" for rhs in cases]
            for data in (
                {key: template, "note": "neutral"},
                {"items": [{key: template}, {key: template}]},
                [{key: template}, {"nested": {key: template}}],
            ):
                texts.extend(json.dumps(data, indent=indent) for indent in (None, 2))
            for index, text in enumerate(texts):
                with self.subTest(template=template, index=index):
                    target.write_text(text)
                    self.assertEqual(self.run_scan()[0], 0)

    def test_template_ambiguous_or_invalid_json_retains_finding(self):
        target = self.root / "note.md"
        key = "to" + "ken"
        for template in ("${EXAMPLE_VALUE}", "{{ EXAMPLE_VALUE }}"):
            property_text = json.dumps(key) + ": " + json.dumps(template)
            obj = "{" + property_text + "}"
            texts = [
                "{" + property_text + ', "note": NaN}',
                "{" + property_text + ', "note": Infinity}',
                "{" + property_text + ', "note": 0, "note": 1}',
                "{" + property_text + ",}",
                "{\n" + property_text + "\n",
                obj + " trailing",
                "[" * 33 + obj + "]" * 33,
                json.dumps({key: template, "note": "a" * (64 * 1024)}),
                "prefix " + key + "=" + template,
                key + "='" + template + "';",
                json.dumps({"command": key + "='" + template + "'"}),
            ]
            for index, text in enumerate(texts):
                with self.subTest(template=template, index=index):
                    target.write_text(text)
                    code, report = self.run_scan()
                    self.assertEqual(code, 1)
                    self.assertIn(
                        "builtin-004", [f["rule_id"] for f in report["findings"]]
                    )

    def test_source_coverage_links_invalid_bytes_and_budget(self):
        import os
        from tools.clean_room_policy import MAX_FILE_BYTES

        for name in (
            ".env",
            ".ignored",
            "CATALOG.md",
            "dist/catalog.json",
            "docs/a.md",
            "tests/f.md",
            ".gitignore",
        ):
            target = self.root / name
            target.parent.mkdir(exist_ok=True)
            target.write_text("Synthetic Quartz")
            self.assertEqual(self.run_scan()[0], 1)
            target.unlink()
        control = self.root / ".git"
        control.mkdir()
        (control / "config").write_text("Synthetic Quartz")
        self.assertEqual(self.run_scan()[0], 0)
        target = self.root / "link"
        target.symlink_to(self.policy)
        self.assertEqual(self.run_scan()[0], 2)
        target.unlink()
        os.mkfifo(target)
        self.assertEqual(self.run_scan()[0], 2)
        target.unlink()
        target.write_bytes(b"\xff\x00")
        self.assertEqual(self.run_scan()[0], 2)
        target.write_bytes(b"a" * (MAX_FILE_BYTES + 1))
        self.assertEqual(self.run_scan()[0], 2)
        target.unlink()
        (self.root / "SYNTHETIC-quartz").mkdir()
        self.assertEqual(self.run_scan()[0], 1)

    def archive(self, kind, members):
        import io
        import tarfile
        import zipfile

        output = io.BytesIO()
        if kind == "zip":
            with zipfile.ZipFile(
                output, "w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                for name, data in members:
                    archive.writestr(name, data)
        else:
            with tarfile.open(
                fileobj=output, mode="w:gz" if kind == "tgz" else "w"
            ) as archive:
                for name, data in members:
                    entry = tarfile.TarInfo(name)
                    entry.size = len(data)
                    if name.endswith("/"):
                        entry.type = tarfile.DIRTYPE
                    archive.addfile(entry, io.BytesIO(data))
        return output.getvalue()

    def test_source_and_zip_share_canonical_collision_rules(self):
        artifact = self.base / "release.zip"
        for names, expected in [(("A.txt", "Ａ.txt"), 2), (("A.txt", "B.txt"), 0)]:
            members = [(name, b"neutral") for name in names]
            artifact.write_bytes(self.archive("zip", members))
            with self.subTest(names=names, inventory="zip"):
                self.assertEqual(self.run_scan(artifact)[0], expected)
            for name, body in members:
                (self.root / name).write_bytes(body)
            with self.subTest(names=names, inventory="source"):
                self.assertEqual(self.run_scan()[0], expected)
            for name in names:
                (self.root / name).unlink()

    def test_archive_content_names_nesting_and_exact_scope(self):
        from tools.clean_room_policy import context_digest

        self.document["allowlist"] = [
            dict(
                rule_id="term-001",
                path="note.md",
                location="content",
                context_sha256=context_digest("Synthetic Quartz", "Synthetic Quartz"),
                justification="Synthetic source-only permission",
            )
        ]
        self.save()
        artifact = self.base / "release.bin"
        for kind in ("zip", "tar", "tgz"):
            with self.subTest(kind=kind):
                artifact.write_bytes(
                    self.archive(kind, [("note.md", b"Synthetic Quartz")])
                )
                code, report = self.run_scan(artifact)
                self.assertEqual(code, 1)
                self.assertGreater(report["unauthorized_findings"], 0)
                artifact.write_bytes(self.archive(kind, [("SYNTHETIC_quartz/", b"")]))
                self.assertEqual(self.run_scan(artifact)[0], 1)
                inner = self.archive("zip", [("note.md", b"Synthetic Quartz")])
                artifact.write_bytes(self.archive(kind, [("inner.data", inner)]))
                self.assertEqual(self.run_scan(artifact)[0], 1)
                artifact.write_bytes(
                    self.archive(kind, [("note.json", b'{"neutral": true}')])
                )
                self.assertEqual(self.run_scan(artifact)[0], 0)
        (self.root / "bundle.zip").write_bytes(
            self.archive("zip", [("x.md", b"Synthetic Quartz")])
        )
        self.assertEqual(self.run_scan()[0], 1)

    def test_archive_safety_rejects_ambiguous_paths_links_and_corruption(self):
        import io
        import tarfile
        import warnings
        import zipfile

        artifact = self.base / "release.zip"
        bad_names = [
            "/absolute",
            "../escape",
            "a/../../escape",
            "C:/drive",
            "a\\backslash",
            "./alias",
            "a//alias",
        ]
        for kind in ("zip", "tar", "tgz"):
            for name in bad_names:
                artifact.write_bytes(self.archive(kind, [(name, b"neutral")]))
                self.assertEqual(self.run_scan(artifact)[0], 2)
            for members in (
                [("a", b"x"), ("a", b"y")],
                [("a", b"x"), ("a/b", b"y")],
                [("A", b"x"), ("a", b"y")],
            ):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    artifact.write_bytes(self.archive(kind, members))
                self.assertEqual(self.run_scan(artifact)[0], 2)
        for kind in (
            tarfile.SYMTYPE,
            tarfile.LNKTYPE,
            tarfile.FIFOTYPE,
            tarfile.CHRTYPE,
        ):
            output = io.BytesIO()
            with tarfile.open(fileobj=output, mode="w") as archive:
                entry = tarfile.TarInfo("link")
                entry.type = kind
                entry.linkname = "elsewhere"
                archive.addfile(entry)
            artifact.write_bytes(output.getvalue())
            self.assertEqual(self.run_scan(artifact)[0], 2)
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            entry = zipfile.ZipInfo("link")
            entry.create_system = 3
            entry.external_attr = 0o120777 << 16
            archive.writestr(entry, "elsewhere")
        artifact.write_bytes(output.getvalue())
        self.assertEqual(self.run_scan(artifact)[0], 2)
        for kind in ("zip", "tar", "tgz"):
            clean = self.archive(kind, [("a", b"neutral")])
            for bad in (clean[:40], clean + b"unscanned trailing payload"):
                artifact.write_bytes(bad)
                self.assertEqual(self.run_scan(artifact)[0], 2)
        nested = b"neutral"
        for _ in range(4):
            nested = self.archive("zip", [("inner.zip" if _ else "a", nested)])
        artifact.write_bytes(nested)
        self.assertEqual(self.run_scan(artifact)[0], 2)

    def test_binary_review_digest_metadata_and_unsupported_formats(self):
        import hashlib

        target = self.root / "asset.ppm"
        data = b"P6\n# neutral author\n1 1\n255\n\xff\x00\x01"
        target.write_bytes(data)
        self.assertEqual(self.run_scan()[0], 2)
        self.document["reviewed_assets"] = [
            dict(
                path="asset.ppm",
                sha256=hashlib.sha256(data).hexdigest(),
                authorship="Synthetic operator",
                license="CC0-1.0",
                metadata_scrubbed=True,
                justification="Synthetic review only",
            )
        ]
        self.save()
        self.assertEqual(self.run_scan()[0], 0)
        changed = data.replace(b"neutral author", b"Synthetic Quartz")
        target.write_bytes(changed)
        self.assertEqual(self.run_scan()[0], 2)
        self.document["reviewed_assets"][0]["sha256"] = hashlib.sha256(
            changed
        ).hexdigest()
        self.save()
        self.assertEqual(self.run_scan()[0], 1)
        self.document["reviewed_assets"][0]["metadata_scrubbed"] = False
        self.save()
        self.assertEqual(self.run_scan()[0], 2)
        self.document["reviewed_assets"][0]["metadata_scrubbed"] = True
        unknown = b"\x89PNG\r\n\x1a\nopaque"
        target.write_bytes(unknown)
        self.document["reviewed_assets"][0]["sha256"] = hashlib.sha256(
            unknown
        ).hexdigest()
        self.save()
        self.assertEqual(self.run_scan()[0], 2)

    def test_cli_deterministic_sanitized_failures_and_no_writes(self):
        import hashlib
        import os
        import subprocess
        import sys

        repo = Path(__file__).resolve().parents[2]

        def snapshot():
            return {
                p.relative_to(self.root).as_posix(): hashlib.sha256(
                    p.read_bytes()
                ).hexdigest()
                for p in self.root.rglob("*")
                if p.is_file()
            }

        (self.root / "note.md").write_text("Synthetic Quartz")
        before = snapshot()
        for entry in (
            [str(repo / "tools/scan_catalog.py")],
            ["-m", "tools.scan_catalog"],
        ):
            command = [
                sys.executable,
                "-B",
                *entry,
                "--root",
                str(self.root),
                "--policy",
                str(self.policy),
                "--json",
            ]
            results = [
                subprocess.run(
                    command,
                    cwd=repo,
                    capture_output=True,
                    text=True,
                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                )
                for _ in range(2)
            ]
            self.assertEqual(results[0].returncode, 1)
            self.assertEqual(results[0].stdout, results[1].stdout)
            self.assertEqual(results[0].stderr, "")
            self.assertEqual(snapshot(), before)
            result = subprocess.run(
                command + ["--sensitive-invalid-argument"],
                cwd=repo,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 2)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "error")
            self.assertNotIn("sensitive", result.stdout + result.stderr)
            self.assertEqual(result.stderr, "")

    def test_findings_budget_and_private_term_mutation_cannot_authorize(self):
        from tools.clean_room_policy import MAX_FINDINGS, context_digest

        target = self.root / "note.md"
        target.write_text("Synthetic Quartz\n" * (MAX_FINDINGS + 1))
        code, report = self.run_scan()
        self.assertEqual(code, 2)
        self.assertLessEqual(len(report["findings"]), MAX_FINDINGS)
        line = "Synthetic Quartz and Other Pebble"
        target.write_text(line)
        self.document["allowlist"] = [
            dict(
                rule_id="term-001",
                path="note.md",
                location="content",
                context_sha256=context_digest(line, "Synthetic Quartz"),
                justification="Synthetic narrow exception",
            )
        ]
        self.save()
        self.assertEqual(self.run_scan()[0], 0)
        self.document["deny_terms"][0]["term"] = "Other Pebble"
        self.save()
        self.assertEqual(self.run_scan()[0], 1)
        self.document["allowlist"][0]["rule_id"] = "builtin-004"
        self.save()
        self.assertEqual(self.run_scan()[0], 2)

    def test_compression_budget_encryption_crc_and_metadata(self):
        import io
        import struct
        import zipfile

        artifact = self.base / "release.zip"
        clean = self.archive("zip", [("a", b"neutral")])
        # Advertised encryption, a bad CRC, and unconsumed deflate bytes must fail.
        encrypted = bytearray(clean)
        central = encrypted.index(b"PK\x01\x02")
        struct.pack_into("<H", encrypted, 6, 1)
        struct.pack_into("<H", encrypted, central + 8, 1)
        corrupt = bytearray(clean)
        corrupt[31] ^= 0xFF
        extra = bytearray(clean)
        compressed = struct.unpack_from("<I", extra, 18)[0]
        extra[31 + compressed : 31 + compressed] = b"junk"
        central += 4
        struct.pack_into("<I", extra, 18, compressed + 4)
        struct.pack_into("<I", extra, central + 20, compressed + 4)
        end = extra.index(b"PK\x05\x06")
        struct.pack_into("<I", extra, end + 16, central)
        for data in (encrypted, corrupt, extra):
            artifact.write_bytes(data)
            self.assertEqual(self.run_scan(artifact)[0], 2)
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            entry = zipfile.ZipInfo("note.md")
            entry.comment = b"Synthetic Quartz"
            archive.writestr(entry, "neutral")
        artifact.write_bytes(output.getvalue())
        self.assertEqual(self.run_scan(artifact)[0], 1)
        artifact.write_bytes(self.archive("zip", [("a", b"a" * 200000)]))
        self.assertEqual(self.run_scan(artifact)[0], 2)

    def test_descriptor_validates_local_fields_before_replacement(self):
        import io
        import struct
        import zipfile

        class Sink(io.BytesIO):
            def seek(self, *args):
                raise io.UnsupportedOperation()

        self.document["deny_terms"][0]["term"] = "Opal"
        self.save()
        artifact = self.base / "release.zip"
        for sink in (io.BytesIO, Sink):
            for method in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                output = sink()
                with zipfile.ZipFile(output, "w", compression=method) as archive:
                    archive.writestr("note.md", b"neutral")
                clean = output.getvalue()
                central = clean.index(b"PK\x01\x02")
                valid = struct.unpack_from("<3I", clean, central + 16)
                descriptor = bool(struct.unpack_from("<H", clean, 6)[0] & 8)
                self.assertEqual(descriptor, sink is Sink)
                controls = [clean]
                if descriptor:
                    for fields in (valid, (valid[0], 0, valid[2])):
                        raw = bytearray(clean)
                        struct.pack_into("<3I", raw, 14, *fields)
                        controls.append(raw)
                for raw in controls:
                    artifact.write_bytes(raw)
                    self.assertEqual(self.run_scan(artifact)[0], 0)
                mutations = [
                    (14, int.from_bytes(b"Opal", "little")),
                    (18, 0xFFFFFFFF),
                    (22, 0xFFFFFFFF),
                    (18, valid[1] + 1),
                    (22, valid[2] + 1),
                ]
                for field, malformed in mutations + [(None, None)]:
                    with self.subTest(
                        descriptor=descriptor, method=method, field=field
                    ):
                        raw = bytearray(clean)
                        if field is None:
                            raw[14:18] = b"Opal"
                            struct.pack_into("<2I", raw, 18, 0xFFFFFFFF, 0xFFFFFFFF)
                        else:
                            struct.pack_into("<I", raw, field, malformed)
                        artifact.write_bytes(raw)
                        self.assertEqual(self.run_scan(artifact)[0], 2)

    def test_archive_allowlist_metadata_has_exact_member_identity(self):
        import hashlib
        import io
        import zipfile
        from tools.clean_room_policy import context_digest

        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            for name in ("one.md", "two.md"):
                entry = zipfile.ZipInfo(name)
                entry.comment = b"Synthetic Quartz"
                archive.writestr(entry, "neutral")
        artifact = self.base / "release.zip"
        artifact.write_bytes(output.getvalue())
        scope = "@artifact/@" + hashlib.sha256(output.getvalue()).hexdigest()
        self.document["allowlist"] = [
            dict(
                rule_id="term-001",
                path=scope + "/one.md",
                location="content",
                context_sha256=context_digest("Synthetic Quartz", "Synthetic Quartz"),
                justification="Synthetic one-member metadata review",
            )
        ]
        self.save()
        code, report = self.run_scan(artifact)
        self.assertEqual(code, 1)
        self.assertEqual(report["authorized_findings"], 1)
        self.assertEqual(report["unauthorized_findings"], 1)
        # Source files cannot impersonate the archive namespace.
        fake = self.root / scope / "one.md"
        fake.parent.mkdir(parents=True)
        fake.write_text("Synthetic Quartz")
        self.assertEqual(self.run_scan()[0], 2)

    def test_policy_regular_file_and_closed_shapes(self):
        import copy
        import os

        self.policy.unlink()
        os.mkfifo(self.policy)
        # Subprocess timeout makes a blocking FIFO read an observable boundary failure.
        import subprocess
        import sys

        repo = Path(__file__).resolve().parents[2]
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "tools.scan_catalog",
                    "--root",
                    str(self.root),
                    "--policy",
                    str(self.policy),
                ],
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=1,
            )
        except subprocess.TimeoutExpired:
            self.fail("policy FIFO was opened instead of rejected")
        self.assertEqual(result.returncode, 2)
        self.policy.unlink()
        original = copy.deepcopy(self.document)
        mutations = [
            ("schema_version", True),
            ("deny_terms", None),
            ("allowlist", {}),
            ("reviewed_assets", [dict(path="asset", extra=True)]),
        ]
        for key, value in mutations:
            self.document = copy.deepcopy(original)
            self.document[key] = value
            self.save()
            self.assertEqual(self.run_scan()[0], 2)
        self.document = original
        self.save()
        hardlink = self.base / "hardlink.json"
        os.link(self.policy, hardlink)
        self.assertEqual(self.run_scan()[0], 2)

    def test_declared_unsupported_containers_and_explicit_artifact_required(self):
        artifact = self.base / "plain.json"
        artifact.write_text('{"neutral": true}')
        self.assertEqual(self.run_scan(artifact)[0], 2)
        for name, data in [
            ("file.bz2", b"BZh9opaque"),
            ("file.gz", b"neutral"),
            ("file.pdf", b"%PDF-1.4\nopaque"),
            ("file.zip", b"neutral"),
        ]:
            target = self.root / name
            target.write_bytes(data)
            self.assertEqual(self.run_scan()[0], 2)
            target.unlink()
        # Signatures take precedence over a misleading text suffix.
        (self.root / "file.md").write_bytes(b"BZh9opaque")
        self.assertEqual(self.run_scan()[0], 2)

    def test_empty_literal_and_separated_assignment_names_are_not_exemptions(self):
        target = self.root / "note.md"
        for value in [
            "pass" + 'word=""',
            "api" + " key = neutral",
            "api" + "-key = neutral",
            "to" + "ken=${EXAMPLE}suffix",
        ]:
            target.write_text(value)
            self.assertEqual(self.run_scan()[0], 1)

    def test_direct_cli_does_not_create_bytecode_or_other_files(self):
        import os
        import shutil
        import subprocess
        import sys

        runner = self.base / "runner"
        runner.mkdir()
        repo = Path(__file__).resolve().parents[2]
        for name in (
            "scan_catalog.py",
            "clean_room_policy.py",
            "clean_room_io.py",
            "clean_room_markers.py",
        ):
            shutil.copyfile(repo / "tools" / name, runner / name)
        before = sorted(p.name for p in runner.iterdir())
        result = subprocess.run(
            [
                sys.executable,
                str(runner / "scan_catalog.py"),
                "--root",
                str(self.root),
                "--policy",
                str(self.policy),
            ],
            capture_output=True,
            env={k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"},
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(sorted(p.name for p in runner.iterdir()), before)

    def test_logical_line_budget_is_fail_closed(self):
        (self.root / "note.md").write_text("\n" * 100001)
        self.assertEqual(self.run_scan()[0], 2)

    def test_documented_policy_and_public_tooling_have_no_credential_fixtures(self):
        import re
        import shutil

        repo = Path(__file__).resolve().parents[2]
        documentation = (repo / "docs/clean-room-scanner.md").read_text(
            encoding="utf-8"
        )
        self.document = json.loads(
            re.search(r"```json\n(.*?)\n```", documentation, re.S)[1]
        )
        self.save()
        self.assertEqual(self.run_scan()[0], 0)
        for path in [
            repo / "tools" / name
            for name in (
                "scan_catalog.py",
                "clean_room_policy.py",
                "clean_room_io.py",
                "clean_room_markers.py",
            )
        ]:
            shutil.copyfile(path, self.root / path.name)
        shutil.copyfile(Path(__file__), self.root / "test_scan_catalog.py")
        (self.root / "guide.md").write_text(documentation, encoding="utf-8")
        code, report = self.run_scan()
        self.assertEqual(
            code, 1
        )  # The documented synthetic term is deliberately present.
        self.assertFalse(
            any(f["rule_id"].startswith("builtin-") for f in report["findings"])
        )

    def test_archive_entry_and_source_total_byte_budgets(self):
        from tools.clean_room_policy import MAX_ENTRIES, MAX_FILE_BYTES

        artifact = self.base / "many.zip"
        artifact.write_bytes(
            self.archive("zip", [(str(n), b"") for n in range(MAX_ENTRIES + 1)])
        )
        self.assertEqual(self.run_scan(artifact)[0], 2)
        # Exactly 64 MiB is admissible; the ninth 8 MiB file crosses total budget.
        # Neutral spaces avoid coupling the resource boundary to any marker rule.
        for n in range(9):
            (self.root / f"{n}.txt").write_bytes(b" " * MAX_FILE_BYTES)
        code, report = self.run_scan()
        self.assertEqual(code, 2)
        self.assertEqual(report["unauthorized_findings"], 0)
        self.assertEqual(report["scanned_entries"], 8)

    def test_directory_names_are_not_silently_canonicalized(self):
        artifact = self.base / "release.zip"
        artifact.write_bytes(self.archive("zip", [("a//", b"")]))
        self.assertEqual(self.run_scan(artifact)[0], 2)
        raw = bytearray(self.archive("tar", [("a/", b"")]))
        raw[:100] = b"a//" + bytes(97)
        raw[148:156] = b" " * 8
        raw[148:156] = f"{sum(raw[:512]):06o}\0 ".encode("ascii")
        artifact.write_bytes(raw)
        self.assertEqual(self.run_scan(artifact)[0], 2)

    def test_supported_raw_archive_metadata_is_inspected(self):
        import io
        import zipfile

        self.document["deny_terms"][0]["term"] = "Opal"
        self.save()
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            entry = zipfile.ZipInfo("note.md")
            entry.extra = b"UT\x05\x00\x01Opal"
            archive.writestr(entry, "neutral")
        artifact = self.base / "release.zip"
        artifact.write_bytes(output.getvalue())
        self.assertEqual(self.run_scan(artifact)[0], 1)
        raw = bytearray(self.archive("tgz", [("note.md", b"neutral")]))
        raw[4:8] = b"Opal"
        artifact.write_bytes(raw)
        self.assertEqual(self.run_scan(artifact)[0], 1)

    def test_archives_share_marker_and_binary_rules_without_side_effects(self):
        import hashlib

        data = b"P6\n1 1\n255\n\xff\x00\x01"
        artifact = self.base / "release.zip"
        payload = self.archive("zip", [("asset.ppm", data)])
        artifact.write_bytes(payload)
        self.assertEqual(self.run_scan(artifact)[0], 2)
        self.document["reviewed_assets"] = [
            dict(
                path="@artifact/@" + hashlib.sha256(payload).hexdigest() + "/asset.ppm",
                sha256=hashlib.sha256(data).hexdigest(),
                authorship="Synthetic operator",
                license="CC0-1.0",
                metadata_scrubbed=True,
                justification="Synthetic archive review",
            )
        ]
        self.save()
        self.assertEqual(self.run_scan(artifact)[0], 0)
        for kind in ("zip", "tar", "tgz"):
            for name, body, expected in [
                (".git/note.md", b"Synthetic Quartz", 1),
                (".env", ("to" + "ken=neutral").encode(), 1),
                ("asset.bin", b"\xff\x00", 2),
                ("note.md", ("http://" + "10." + "4.5.6").encode(), 1),
                ("malformed\nname", b"neutral", 2),
            ]:
                with self.subTest(kind=kind, expected=expected):
                    artifact.write_bytes(self.archive(kind, [(name, body)]))
                    before = artifact.read_bytes()
                    code, report = self.run_scan(artifact)
                    self.assertEqual(code, expected)
                    self.assertEqual(artifact.read_bytes(), before)
                    self.assertNotIn(name, json.dumps(report))
                    self.assertEqual(list(self.root.iterdir()), [])

    def test_nested_policy_mutations_and_path_allowlist(self):
        import copy
        from tools.clean_room_policy import context_digest

        original = copy.deepcopy(self.document)
        bad_rules = [
            dict(id="term-001", term="abc", classification="origin"),
            dict(id="term-001", term="neutral", classification="unknown"),
            dict(id="term-001", term="neutral", classification="origin", extra=0),
        ]
        for rule in bad_rules:
            self.document = copy.deepcopy(original)
            self.document["deny_terms"] = [rule]
            self.save()
            self.assertEqual(self.run_scan()[0], 2)
        self.document = copy.deepcopy(original)
        self.document["deny_terms"].append(
            dict(id="term-002", term="SYNTHETIC-quartz", classification="tenant")
        )
        self.save()
        self.assertEqual(self.run_scan()[0], 2)
        self.document = copy.deepcopy(original)
        name = "Synthetic-quartz.md"
        (self.root / name).write_text("neutral")
        self.document["allowlist"] = [
            dict(
                rule_id="term-001",
                path=name,
                location="path",
                context_sha256=context_digest(name, "Synthetic Quartz", "path"),
                justification="Synthetic exact path review",
            )
        ]
        self.save()
        self.assertEqual(self.run_scan()[0], 0)
        (self.root / name).write_text("Synthetic Quartz")
        code, report = self.run_scan()
        self.assertEqual(code, 1)
        self.assertEqual(report["authorized_findings"], 1)
        self.assertEqual(report["unauthorized_findings"], 1)

    def test_repeated_matches_on_one_line_have_bounded_work(self):
        import subprocess
        import sys

        (self.root / "note.md").write_text("Synthetic Quartz " * 10001)
        repo = Path(__file__).resolve().parents[2]
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "tools.scan_catalog",
                    "--root",
                    str(self.root),
                    "--policy",
                    str(self.policy),
                ],
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            self.fail("repeated same-line contexts exhausted the work budget")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["unauthorized_findings"], 10000)

    def test_opaque_binary_archive_comments_are_rejected(self):
        import io
        import zipfile

        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.comment = b"opaque\x00metadata"
            archive.writestr("note.md", "neutral")
        artifact = self.base / "release.zip"
        artifact.write_bytes(output.getvalue())
        self.assertEqual(self.run_scan(artifact)[0], 2)
