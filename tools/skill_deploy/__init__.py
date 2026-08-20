"""Declarative skill deployment controller (Phase 0/1).

Provides read-only inventory and deterministic plan generation for governed skills.
"""

from .inventory import build_inventory
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
    "build_inventory",
    "compile_plan",
    "DeploymentPlan",
    "DeploymentParseError",
    "DeploymentMatrix",
    "DeploymentPolicy",
    "load_matrix",
    "load_plan_json",
    "load_policy",
    "MatrixEntry",
    "MatrixProfile",
    "PolicyProfile",
    "RegistrySkill",
    "write_plan_json",
]
