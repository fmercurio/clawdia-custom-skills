"""Declarative skill deployment controller (Phase 0/1/2).

Provides read-only inventory, deterministic plan generation, and Phase 2 audit/manifest helpers.
"""

from .audit_gate import AuditReport, audit_paths, audit_paths_json
from .inventory import build_inventory
from .manifest import (
    DeploymentManifest,
    ManifestVerification,
    create_manifest,
    load_manifest_json,
    verify_manifest,
    write_manifest_json,
)
from .plan import DeploymentPlan, load_plan_json, write_plan_json, compile_plan
from .policy import (
    DeploymentMatrix,
    DeploymentParseError,
    DeploymentPolicy,
    MatrixEntry,
    MatrixProfile,
    PolicyProfile,
    RegistrySkill,
    load_matrix,
    load_policy,
)

__all__ = [
    "audit_paths",
    "audit_paths_json",
    "AuditReport",
    "build_inventory",
    "compile_plan",
    "DeploymentPlan",
    "DeploymentManifest",
    "DeploymentParseError",
    "DeploymentMatrix",
    "DeploymentPolicy",
    "create_manifest",
    "load_matrix",
    "load_manifest_json",
    "load_plan_json",
    "load_policy",
    "ManifestVerification",
    "MatrixEntry",
    "MatrixProfile",
    "PolicyProfile",
    "RegistrySkill",
    "verify_manifest",
    "write_manifest_json",
    "write_plan_json",
]
