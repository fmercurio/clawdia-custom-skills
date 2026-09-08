"""Synthetic, exact occurrence reviews through the public scanner API."""

import copy
import hashlib
import io
import json
import zipfile
from pathlib import Path
import tempfile
import tarfile
import gzip
import unittest

from tools.scan_catalog import Scanner, scan
from tools.clean_room_policy import (
    MAX_FINDINGS,
    MAX_LINES,
    POLICY_BYTES,
    InvalidInput,
    load_policy,
    context_digest,
)


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "source"
        self.root.mkdir()
        self.raw = ("password" + "=synthetic-value\n").encode()
        (self.root / "sample.txt").write_bytes(self.raw)
        self.review = dict(
            rule_id="builtin-004",
            path="sample.txt",
            location="content",
            line=1,
            occurrence=1,
            content_sha256=hashlib.sha256(self.raw).hexdigest(),
            decision="false_positive",
            review_id="review-000001",
            justification="Synthetic test review",
        )
        self.policy = dict(
            schema_version="clean-room-policy/v2",
            deny_terms=[
                dict(id="term-001", term="Synthetic Quartz", classification="origin")
            ],
            allowlist=[],
            reviewed_assets=[],
            builtin_reviews=[self.review],
        )

    def run_scan(self, archives=()):
        path = self.base / "policy.json"
        path.write_text(json.dumps(self.policy), encoding="utf-8")
        return scan(self.root, path, archives)

    def test_exact_review(self):
        code, report = self.run_scan()
        self.assertEqual(code, 0, report)
        self.assertEqual(report["authorized_findings"], 1)

    def test_strict_review_loader(self):
        self.assertEqual(self.run_scan()[0], 0)
        valid = copy.deepcopy(self.policy)
        mutations = []
        for field in self.review:
            entry = dict(self.review)
            del entry[field]
            mutations.append([entry])
        invalid = {
            "rule_id": ["builtin-001", "builtin-003", "term-001", [], None],
            "path": [
                "/absolute",
                "../escape",
                "a//b",
                "a/./b",
                "a/*",
                "a/../b",
                "a/ b",
                "a\\b",
                "a:b",
                "a?",
                "a[0]",
                "a!",
                "",
                True,
            ],
            "location": ["path", "metadata", None, []],
            "line": [True, False, 0, -1, MAX_LINES + 1, 1.0, "1", None],
            "occurrence": [True, 0, -1, MAX_FINDINGS + 1, 1.0, "1", None],
            "content_sha256": ["A" * 64, "0" * 63, "g" * 64, None, 0],
            "decision": ["approved", True, None],
            "review_id": ["review-1", "review-0000000", "private-name", None, 1],
            "justification": [
                "short",
                "x" * 1025,
                " padded review",
                "bad\nreview",
                None,
            ],
        }
        for field, values in invalid.items():
            mutations.extend([{**self.review, field: value}] for value in values)
        mutations.extend(
            [
                [{**self.review, "extra": 1}],
                [self.review, dict(self.review)],
                [
                    self.review,
                    {
                        **self.review,
                        "review_id": "review-000002",
                        "content_sha256": "0" * 64,
                    },
                ],
                [self.review, {**self.review, "path": "other.txt"}],
                None,
                {},
                [None],
                [self.review] * (MAX_FINDINGS + 1),
            ]
        )
        for index, entries in enumerate(mutations):
            with self.subTest(index=index):
                self.policy = copy.deepcopy(valid)
                self.policy["builtin_reviews"] = entries
                self.assertEqual(self.run_scan()[0], 2)
                with self.assertRaises(InvalidInput):
                    load_policy(self.root, self.base / "policy.json")
        self.policy = valid
        self.assertEqual(self.run_scan()[0], 0)

    def test_stale_review_invalidates_completed_scan(self):
        self.assertEqual(self.run_scan()[0], 0)
        valid = dict(self.review)
        for field, value in [
            ("path", "renamed.txt"),
            ("rule_id", "builtin-005"),
            ("line", 2),
            ("occurrence", 2),
            ("content_sha256", "0" * 64),
        ]:
            with self.subTest(field=field):
                self.review.clear()
                self.review.update(valid)
                self.review[field] = value
                code, report = self.run_scan()
                self.assertEqual(code, 2)
                self.assertEqual(report["error"], "invalid_input")
                self.assertEqual(report["unauthorized_findings"], 1)
        self.review.clear()
        self.review.update(valid)
        (self.root / "sample.txt").write_bytes(b"neutral text")
        (self.root / "z-other.txt").write_bytes(self.raw)
        code, report = self.run_scan()
        self.assertEqual(code, 2)
        self.assertEqual(report["scanned_entries"], 2)
        self.assertEqual(report["unauthorized_findings"], 1)
        (self.root / "z-other.txt").unlink()
        self.assertEqual(self.run_scan()[0], 2)
        (self.root / "sample.txt").unlink()
        self.assertEqual(self.run_scan()[0], 2)

    def zip_bytes(self, name, raw, comment=b""):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(name, raw)
            archive.comment = comment
        return buffer.getvalue()

    def test_review_reuse_is_error_and_scan_continues(self):
        (self.root / "sample.txt").unlink()
        raw = self.zip_bytes("sample.txt", self.raw)
        archive = self.base / "bundle.zip"
        archive.write_bytes(raw)
        self.review["path"] = (
            "@artifact/@" + hashlib.sha256(raw).hexdigest() + "/sample.txt"
        )
        self.assertEqual(self.run_scan([archive])[0], 0)
        other = self.base / "other.zip"
        other.write_bytes(self.zip_bytes("other.txt", self.raw))
        code, report = self.run_scan([archive, archive, other])
        self.assertEqual(code, 2)
        self.assertEqual(report["error"], "invalid_input")
        self.assertEqual(len(report["findings"]), 3)
        self.assertEqual(report["authorized_findings"], 1)
        self.assertEqual(report["unauthorized_findings"], 2)
        self.assertEqual(self.run_scan([archive])[0], 0)

    def test_duplicate_ordinals_and_report_versions(self):
        raw = self.raw.rstrip() + b"; " + self.raw
        (self.root / "sample.txt").write_bytes(raw)
        self.review["content_sha256"] = hashlib.sha256(raw).hexdigest()
        code, report = self.run_scan()
        self.assertEqual(code, 1)
        self.assertEqual(report["schema_version"], "clean-room-report/v2")
        self.assertEqual(
            [(f["occurrence"], f["authorized"]) for f in report["findings"]],
            [(1, True), (2, False)],
        )
        self.review["occurrence"] = 2
        code, report = self.run_scan()
        self.assertEqual(code, 1)
        self.assertEqual(
            [(f["occurrence"], f["authorized"]) for f in report["findings"]],
            [(1, False), (2, True)],
        )
        self.policy["builtin_reviews"].append(
            {**self.review, "occurrence": 1, "review_id": "review-000002"}
        )
        self.assertEqual(self.run_scan()[0], 0)
        self.policy["schema_version"] = "clean-room-policy/v1"
        self.assertEqual(self.run_scan()[0], 2)
        del self.policy["builtin_reviews"]
        code, report = self.run_scan()
        self.assertEqual(code, 1)
        self.assertEqual(report["schema_version"], "clean-room-report/v1")
        self.assertEqual(report["unauthorized_findings"], 2)
        self.assertTrue(all("occurrence" not in f for f in report["findings"]))

    def test_raw_utf8_binding_survives_no_byte_changes(self):
        raw = self.raw + "Café\n".encode()
        (self.root / "sample.txt").write_bytes(raw)
        self.review["content_sha256"] = hashlib.sha256(raw).hexdigest()
        self.assertEqual(self.run_scan()[0], 0)
        for changed in (
            raw.replace(b"\n", b"\r\n"),
            raw.replace("é".encode(), "e\u0301".encode()),
            raw + b"unrelated line\n",
            raw.replace(b"password", "ｐａｓｓｗｏｒｄ".encode()),
        ):
            with self.subTest(changed=changed):
                (self.root / "sample.txt").write_bytes(changed)
                code, report = self.run_scan()
                self.assertEqual(code, 2)
                self.assertEqual(report["unauthorized_findings"], 1)
                self.assertEqual(report["authorized_findings"], 0)
                original_hash = self.review["content_sha256"]
                self.review["content_sha256"] = hashlib.sha256(changed).hexdigest()
                self.assertEqual(self.run_scan()[0], 0)
                self.review["content_sha256"] = original_hash

    def test_nested_archive_identity_binds_all_containers(self):
        (self.root / "sample.txt").unlink()
        inner = self.zip_bytes("sample.txt", self.raw)
        outer = self.zip_bytes("inner.zip", inner)
        bundle = self.root / "bundle.zip"
        bundle.write_bytes(outer)
        identity = (
            "bundle.zip/@"
            + hashlib.sha256(outer).hexdigest()
            + "/inner.zip/@"
            + hashlib.sha256(inner).hexdigest()
            + "/sample.txt"
        )
        self.review["path"] = identity
        self.assertEqual(self.run_scan()[0], 0)
        for path in (
            "sample.txt",
            "inner.zip/sample.txt",
            identity.replace("/inner.zip/@", "/@"),
            identity.replace("bundle.zip/", "@artifact/", 1),
        ):
            self.review["path"] = path
            code, report = self.run_scan()
            self.assertEqual(code, 2)
            self.assertEqual(report["unauthorized_findings"], 1)
        self.review["path"] = identity
        bundle.write_bytes(self.zip_bytes("inner.zip", inner, b"neutral change"))
        self.assertEqual(self.run_scan()[0], 2)
        bundle.write_bytes(outer)
        self.assertEqual(self.run_scan()[0], 0)
        changed_inner = self.zip_bytes("sample.txt", self.raw, b"neutral change")
        changed_outer = self.zip_bytes("inner.zip", changed_inner)
        bundle.write_bytes(changed_outer)
        self.review["path"] = identity.replace(
            hashlib.sha256(outer).hexdigest(), hashlib.sha256(changed_outer).hexdigest()
        )
        self.assertEqual(self.run_scan()[0], 2)
        self.review["path"] = self.review["path"].replace(
            hashlib.sha256(inner).hexdigest(), hashlib.sha256(changed_inner).hexdigest()
        )
        self.assertEqual(self.run_scan()[0], 0)

    def test_tar_and_gzip_text_members(self):
        (self.root / "sample.txt").unlink()
        buffer = io.BytesIO()
        with tarfile.open(
            fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT
        ) as archive:
            member = tarfile.TarInfo("sample.txt")
            member.size = len(self.raw)
            archive.addfile(member, io.BytesIO(self.raw))
        tar = buffer.getvalue()
        for name, raw in [
            ("bundle.tar", tar),
            ("bundle.tgz", gzip.compress(tar, mtime=0)),
        ]:
            path = self.root / name
            path.write_bytes(raw)
            self.review["path"] = (
                name + "/@" + hashlib.sha256(raw).hexdigest() + "/sample.txt"
            )
            self.assertEqual(self.run_scan()[0], 0)
            self.review["path"] = "sample.txt"
            self.assertEqual(self.run_scan()[0], 2)
            path.unlink()

    def test_metadata_cannot_consume_member_review(self):
        (self.root / "sample.txt").unlink()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            member = zipfile.ZipInfo("sample.txt")
            member.comment = self.raw
            archive.writestr(member, self.raw)
        raw = buffer.getvalue()
        (self.root / "bundle.zip").write_bytes(raw)
        self.review["path"] = (
            "bundle.zip/@" + hashlib.sha256(raw).hexdigest() + "/sample.txt"
        )
        code, report = self.run_scan()
        self.assertEqual(code, 1)
        self.assertEqual(report["authorized_findings"], 1)
        self.assertEqual(report["unauthorized_findings"], 1)
        # Same bytes, identity, line and ordinal occur in both blocks. Only the
        # member body may consume the review; metadata is not text payload.
        self.assertIsNone(report["error"])
        raw = self.zip_bytes("neutral.txt", b"neutral", self.raw)
        (self.root / "bundle.zip").write_bytes(raw)
        self.review["path"] = "bundle.zip/@" + hashlib.sha256(raw).hexdigest()
        code, report = self.run_scan()
        self.assertEqual(code, 2)
        self.assertEqual(report["authorized_findings"], 0)
        self.assertEqual(report["unauthorized_findings"], 1)

    def test_binary_and_unbound_inspection_cannot_consume_review(self):
        self.assertEqual(self.run_scan()[0], 0)
        scanner = Scanner(self.policy)
        scanner.inspect("sample.txt", "content", self.raw.decode())
        code, report = scanner.report()
        self.assertEqual(code, 2)
        self.assertEqual(report["authorized_findings"], 0)
        scanner = Scanner(self.policy)
        scanner.inspect(
            "sample.txt",
            "path",
            self.raw.decode(),
            content_sha256=self.review["content_sha256"],
        )
        self.assertEqual(scanner.report()[1]["authorized_findings"], 0)
        raw = b"P6\n# " + self.raw + b"1 1\n255\nabc"
        (self.root / "sample.txt").write_bytes(raw)
        self.review.update(line=2, content_sha256=hashlib.sha256(raw).hexdigest())
        self.policy["reviewed_assets"] = [
            dict(
                path="sample.txt",
                sha256=hashlib.sha256(raw).hexdigest(),
                authorship="Synthetic authorship",
                license="CC0",
                metadata_scrubbed=True,
                justification="Synthetic asset review",
            )
        ]
        code, report = self.run_scan()
        self.assertEqual(code, 2)
        self.assertEqual(report["authorized_findings"], 0)
        self.assertEqual(report["unauthorized_findings"], 1)
        self.policy["builtin_reviews"] = []
        self.assertEqual(self.run_scan()[0], 1)

    def test_reviewable_rules_and_redacted_reports(self):
        samples = {
            "builtin-002": ("-----BEGIN " + "PRIVATE KEY-----").encode(),
            "builtin-004": self.raw,
            "builtin-005": ("/" + "home/" + "synthetic-user/file").encode(),
            "builtin-006": ".".join(["10", "23", "45", "67"]).encode(),
        }
        for rule, raw in samples.items():
            self.review.update(
                rule_id=rule, content_sha256=hashlib.sha256(raw).hexdigest()
            )
            (self.root / "sample.txt").write_bytes(raw)
            code, report = self.run_scan()
            self.assertEqual(code, 0, report)
            self.assertEqual(report["authorized_findings"], 1)
            for change in (False, True):
                if change:
                    (self.root / "sample.txt").write_bytes(raw + b" changed")
                    code, report = self.run_scan()
                    self.assertEqual(code, 2)
                output = json.dumps(report)
                for private in (
                    raw.decode(),
                    self.review["path"],
                    str(self.root),
                    self.review["content_sha256"],
                    self.review["review_id"],
                    self.review["justification"],
                ):
                    self.assertNotIn(private, output)
                for finding in report["findings"]:
                    self.assertEqual(
                        set(finding),
                        {
                            "rule_id",
                            "path_id",
                            "location",
                            "line",
                            "occurrence",
                            "authorized",
                        },
                    )

    def test_v1_terms_and_v2_empty_reviews_preserve_contract(self):
        raw = b"Synthetic Quartz\n"
        (self.root / "sample.txt").write_bytes(raw)
        self.policy["builtin_reviews"] = []
        self.policy["allowlist"] = [
            dict(
                rule_id="term-001",
                path="sample.txt",
                location="content",
                context_sha256=context_digest(raw.decode().strip(), "Synthetic Quartz"),
                justification="Synthetic term review",
            )
        ]
        code, report = self.run_scan()
        self.assertEqual(code, 0)
        self.assertEqual(report["authorized_findings"], 1)
        self.assertNotIn("occurrence", report["findings"][0])
        self.policy["schema_version"] = "clean-room-policy/v1"
        del self.policy["builtin_reviews"]
        code, legacy = self.run_scan()
        self.assertEqual(code, 0)
        self.assertEqual(report["findings"], legacy["findings"])
        self.policy["allowlist"][0]["rule_id"] = "builtin-004"
        self.assertEqual(self.run_scan()[0], 2)

    def test_closed_v2_top_level_and_policy_budget(self):
        self.assertEqual(self.run_scan()[0], 0)
        valid = copy.deepcopy(self.policy)
        for field in valid:
            self.policy = copy.deepcopy(valid)
            del self.policy[field]
            self.assertEqual(self.run_scan()[0], 2)
        self.policy = copy.deepcopy(valid)
        self.policy["extra"] = []
        self.assertEqual(self.run_scan()[0], 2)
        self.policy = valid
        self.run_scan()
        path = self.base / "policy.json"
        raw = path.read_bytes()
        for invalid in (
            raw[:-1] + b',"builtin_reviews":[]}',
            raw + b" " * POLICY_BYTES,
        ):
            path.write_bytes(invalid)
            self.assertEqual(scan(self.root, path)[0], 2)
        # Loader accepts the inclusive numeric boundaries, independent of
        # whether such an occurrence exists in this small text fixture.
        self.review = self.policy["builtin_reviews"][0]
        self.review.update(line=MAX_LINES, occurrence=MAX_FINDINGS)
        self.run_scan()
        self.assertEqual(load_policy(self.root, path), self.policy)


if __name__ == "__main__":
    unittest.main()
