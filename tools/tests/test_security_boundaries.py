from __future__ import annotations

import os
from pathlib import Path
import stat
import tempfile
import unittest

from tools.security_boundaries import (
    BoundaryError,
    ResourceBudget,
    admit_payload,
    require_capability,
    safe_write_bytes_beneath,
    validate_public_https_origin,
    validate_service_identifier,
)


class SecurityBoundaryTests(unittest.TestCase):
    def test_service_identifier_rejects_template_and_path_syntax(self):
        self.assertEqual(validate_service_identifier("second-brain-readonly"), "second-brain-readonly")
        for value in ("bad\nExecStart=/bin/sh", "<plist>", "../escape", "UPPER"):
            with self.assertRaises(BoundaryError):
                validate_service_identifier(value)

    def test_payload_budget_rejects_excess_before_admission(self):
        budget = ResourceBudget(max_bytes=8, max_items=2)
        admit_payload(byte_count=8, item_count=2, budget=budget)
        with self.assertRaisesRegex(BoundaryError, "byte budget"):
            admit_payload(byte_count=9, item_count=1, budget=budget)
        with self.assertRaisesRegex(BoundaryError, "item budget"):
            admit_payload(byte_count=1, item_count=3, budget=budget)

    def test_public_origin_requires_approved_host_and_global_addresses(self):
        self.assertEqual(
            validate_public_https_origin(
                "https://share.example.test/folder", allowed_origins=[("share.example.test", 443)], resolved_addresses=["8.8.8.8"]
            ),
            "share.example.test",
        )
        with self.assertRaises(BoundaryError):
            validate_public_https_origin(
                "https://share.example.test/folder", allowed_origins=[("share.example.test", 443)], resolved_addresses=["127.0.0.1"]
            )
        with self.assertRaises(BoundaryError):
            validate_public_https_origin(
                "https://user:pass@share.example.test/folder", allowed_origins=[("share.example.test", 443)], resolved_addresses=["8.8.8.8"]
            )
        with self.assertRaisesRegex(BoundaryError, "origin is not approved"):
            validate_public_https_origin(
                "https://share.example.test:444/folder", allowed_origins=[("share.example.test", 443)], resolved_addresses=["8.8.8.8"]
            )

    def test_capability_is_exact_and_explicit(self):
        require_capability("brain.restricted-search", {"brain.restricted-search"})
        with self.assertRaisesRegex(BoundaryError, "missing required capability"):
            require_capability("brain.restricted-search", set())

    def test_safe_write_rejects_symlink_leaf_and_preserves_owner_mode(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "root"
            root.mkdir(mode=0o700)
            target = safe_write_bytes_beneath(root, Path("nested") / "state.json", b"ok")
            self.assertEqual(target.read_bytes(), b"ok")
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            outside = Path(raw) / "outside"
            outside.write_bytes(b"sentinel")
            linked = root / "linked"
            linked.symlink_to(outside)
            with self.assertRaises((BoundaryError, OSError)):
                safe_write_bytes_beneath(root, Path("linked"), b"mutated", overwrite=True)
            self.assertEqual(outside.read_bytes(), b"sentinel")


if __name__ == "__main__":
    unittest.main()
