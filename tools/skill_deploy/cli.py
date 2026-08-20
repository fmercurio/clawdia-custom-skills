from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__:
    from . import build_inventory, compile_plan, load_plan_json, write_plan_json
    from .inventory import InventoryItem
    from .plan import DeploymentPlan
    from .policy import DeploymentParseError, load_matrix, load_policy
else:
    REPO_ROOT = Path(__file__).resolve().parents[2]
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    from tools.skill_deploy import build_inventory, compile_plan, load_plan_json, write_plan_json
    from tools.skill_deploy.inventory import InventoryItem
    from tools.skill_deploy.plan import DeploymentPlan
    from tools.skill_deploy.policy import DeploymentParseError, load_matrix, load_policy


def _default_policy_path() -> Path:
    return Path.home() / ".hermes" / "skills-lab" / "skill-deployment-policy.json"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Skill deployment planner (read-only controller)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    inventory_cmd = sub.add_parser("inventory", help="Collect inventory for a profile")
    inventory_cmd.add_argument("--policy", type=Path, default=_default_policy_path())
    inventory_cmd.add_argument("--profile", required=True)
    inventory_cmd.add_argument("--format", choices=["json", "text"], default="json")
    inventory_cmd.add_argument("--root", type=Path, default=Path.cwd())
    inventory_cmd.add_argument("--skills-lab-root", type=Path, default=None)
    inventory_cmd.add_argument("--hermes-home", type=Path, default=None)

    plan_cmd = sub.add_parser("plan", help="Generate deterministic non-destructive plan")
    plan_cmd.add_argument("--policy", type=Path, default=_default_policy_path())
    plan_cmd.add_argument("--profile", required=True)
    plan_cmd.add_argument("--out", type=Path, default=None)
    plan_cmd.add_argument("--strict", action="store_true", help="Non-zero if any blocked operation")
    plan_cmd.add_argument("--root", type=Path, default=Path.cwd())
    plan_cmd.add_argument("--skills-lab-root", type=Path, default=None)
    plan_cmd.add_argument("--hermes-home", type=Path, default=None)

    explain_cmd = sub.add_parser("explain", help="Explain an existing plan JSON")
    explain_cmd.add_argument("plan_file", type=Path)

    return parser


def _inventory_to_json_payload(
    items: list[InventoryItem],
    duplicates: list[str],
    profile_name: str,
) -> dict:
    return {
        "profile": profile_name,
        "items": [
            {
                "name": item.name,
                "category": item.category,
                "source_type": item.source_type,
                "path": item.path,
                "skill_md_name": item.skill_md_name,
                "sha256": item.sha256,
                "destination": item.destination,
                "availability": item.availability,
                "avoid_by_default": item.avoid_by_default,
            }
            for item in items
        ],
        "duplicates": duplicates,
    }


def _run_inventory(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    policy_path = args.policy

    try:
        policy = load_policy(policy_path, root=root)
        matrix = load_matrix(policy.inputs.matrix_path or (Path.home() / ".hermes" / "skills-lab" / "profile-skill-matrix.yaml"), root=root)
        report = build_inventory(
            matrix=matrix,
            profile_name=args.profile,
            canonical_registry_path=policy.inputs.canonical_registry_path
            or (Path.home() / ".hermes" / "custom-skills" / "registry" / "skills-registry.yaml"),
            runtime_registry_path=policy.inputs.runtime_registry_path
            or (Path.home() / ".hermes" / "skills-lab" / "skills-registry.yaml"),
            root=root,
            hermes_home=args.hermes_home or policy.inputs.hermes_home or (Path.home() / ".hermes"),
            skills_lab_root=args.skills_lab_root,
        )
    except DeploymentParseError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    items = report["items"]
    duplicates = report["duplicates"]
    payload = _inventory_to_json_payload(items, duplicates, args.profile)  # type: ignore[arg-type]

    if args.format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Profile: {args.profile}")
        print(f"Items: {len(items)}")
        for name in duplicates:
            print(f"DUPLICATE: {name}")
    return 0


def _run_plan(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    policy_path = args.policy

    try:
        plan = compile_plan(
            policy_path=policy_path,
            profile_name=args.profile,
            workspace_root=root,
            hermes_home=args.hermes_home,
            skills_lab_root=args.skills_lab_root,
        )

        if args.out is not None:
            write_plan_json(plan, args.out)
            print(f"Wrote plan to {args.out}")
        else:
            print(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
    except DeploymentParseError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.strict and plan.blocked:
        print(f"ERROR: strict mode blocked with {len(plan.blocked)} item(s)", file=sys.stderr)
        return 1

    return 0


def _run_explain(args: argparse.Namespace) -> int:
    try:
        plan = load_plan_json(args.plan_file)
    except (OSError, ValueError, KeyError) as exc:
        print(f"ERROR: cannot read plan: {exc}", file=sys.stderr)
        return 1

    blocked = sum(1 for op in plan.operations if op.action == "blocked")
    manual = sum(1 for op in plan.operations if op.action == "manual-review")
    ready = sum(
        1
        for op in plan.operations
        if op.action in {"noop", "install-copy", "skip-local", "blocked"}
    )

    print(f"Profile: {plan.profile}")
    print(f"Plan ID: {plan.plan_id}")
    print(f"Created at: {plan.created_at}")
    print(f"Operations: {len(plan.operations)}")
    print(f"  blocked: {blocked}")
    print(f"  manual-review: {manual}")
    print(f"  ready: {ready}")
    print("---")

    for op in plan.operations:
        print(f"[{op.action}] {op.skill} -> {op.destination}")
        print(f"  reason: {op.reason}")
        if not op.preconditions:
            print("  preconditions: none")
            continue
        for precondition in op.preconditions:
            mark = "\u2713" if precondition.satisfied else "!"
            print(
                f"  {mark} {precondition.name}: expected={precondition.expected} actual={precondition.actual}"
            )

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "inventory":
        return _run_inventory(args)
    if args.command == "plan":
        return _run_plan(args)
    if args.command == "explain":
        return _run_explain(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
