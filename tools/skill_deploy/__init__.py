"""Declarative skill deployment controller (Phase 0/1/2/3 sandbox-only).

Provides read-only inventory, deterministic plan generation, Phase 2 audit/manifest helpers,
and Phase 3 sandbox-only apply/verify/rollback helpers under a temp-root sandbox.
"""

from .apply import apply_manifest
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
from .rollback import rollback_manifest
from .runtime_verify import verify_applied_state

__all__ = [
    "apply_manifest",
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
    "rollback_manifest",
    "verify_applied_state",
    "verify_manifest",
    "write_manifest_json",
    "write_plan_json",
]
