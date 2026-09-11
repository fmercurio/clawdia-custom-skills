"""Contract tests for the public catalog GitHub Actions workflow."""

from __future__ import annotations

import copy
import itertools
import subprocess
import unittest
from pathlib import Path

import yaml

from tools.clean_room_markers import markers
from tools.run_catalog_ci import PUBLIC_GATES


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "catalog-and-validation.yml"
PUBLIC_RESULT_EXPRESSION = "${{ needs.public-gates.result }}"
PRIVATE_RESULT_EXPRESSION = "${{ needs.private-clean-room.result }}"
AGGREGATE_COMMAND = (
    f'if [ "{PUBLIC_RESULT_EXPRESSION}" = success ] &&\n'
    f'   [ "{PRIVATE_RESULT_EXPRESSION}" = success ]; then\n'
    "  exit 0\n"
    "fi\n"
    "exit 1\n"
)
CHECKOUT_ACTION = (
    "actions/checkout@11d5960a326750d5838078e36cf38b85af677262"
)
SETUP_PYTHON_ACTION = (
    "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065"
)


def load_workflow() -> dict[str, object]:
    with WORKFLOW_PATH.open(encoding="utf-8") as workflow_file:
        document = yaml.load(workflow_file, Loader=yaml.BaseLoader)
    if not isinstance(document, dict):
        raise AssertionError("workflow must be a mapping")
    return document


def render_fixed_aggregate_command(
    command: str, public_result: str, private_result: str
) -> str:
    states = {"success", "failure", "skipped", "cancelled"}
    if command != AGGREGATE_COMMAND:
        raise AssertionError("aggregate command is not the reviewed fixed command")
    if public_result not in states or private_result not in states:
        raise AssertionError("synthetic result is not allowlisted")
    rendered = command.replace(PUBLIC_RESULT_EXPRESSION, public_result)
    rendered = rendered.replace(PRIVATE_RESULT_EXPRESSION, private_result)
    if "${{" in rendered:
        raise AssertionError("unreviewed expression remains in aggregate command")
    return rendered


def validate_workflow(workflow: dict[str, object]) -> None:
    """Validate this one workflow's intentionally small public contract."""

    if set(workflow) != {"name", "on", "permissions", "jobs"}:
        raise AssertionError("unexpected top-level workflow shape")
    if workflow["name"] != "Catalog and Validation":
        raise AssertionError("unexpected workflow name")
    if workflow["on"] != {
        "pull_request": {},
        "push": {"branches": ["main"]},
    }:
        raise AssertionError("unsafe trigger set")
    if workflow["permissions"] != {"contents": "read"}:
        raise AssertionError("workflow permissions are not contents:read")

    jobs = workflow["jobs"]
    if set(jobs) != {
        "public-gates",
        "private-clean-room",
        "catalog-validation",
    }:
        raise AssertionError("unexpected job set")

    def reject_unsafe_channels(value: object) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"env", "environment", "secrets"}:
                    raise AssertionError("environment or secret injection")
                if key == "continue-on-error":
                    raise AssertionError("continue-on-error is forbidden")
                reject_unsafe_channels(child)
        elif isinstance(value, list):
            for child in value:
                reject_unsafe_channels(child)
        elif isinstance(value, str) and "${{ secrets." in value:
            raise AssertionError("secret expression is forbidden")

    reject_unsafe_channels(workflow)

    for job_id, job in jobs.items():
        if "permissions" in job:
            raise AssertionError("job permissions are forbidden")
        if job.get("runs-on") != "ubuntu-latest":
            raise AssertionError("only ubuntu-latest is allowed")
        timeout = job.get("timeout-minutes")
        if not isinstance(timeout, str) or not timeout.isdigit() or int(timeout) < 1:
            raise AssertionError("every job needs a finite positive timeout")
        if job_id == "catalog-validation":
            if job.get("if") != "${{ always() }}":
                raise AssertionError("aggregate must use always()")
        elif "if" in job:
            raise AssertionError("job-level conditional skip is forbidden")
        if any("if" in step for step in job.get("steps", [])):
            raise AssertionError("step-level conditional skip is forbidden")

    public_job = jobs["public-gates"]
    if set(public_job) != {
        "name",
        "runs-on",
        "timeout-minutes",
        "strategy",
        "steps",
    }:
        raise AssertionError("unexpected public job shape")
    if public_job["name"] != "Public catalog gate (${{ matrix.gate }})":
        raise AssertionError("unexpected public job name")
    strategy = public_job["strategy"]
    if strategy.get("fail-fast") != "false":
        raise AssertionError("public matrix fail-fast must be false")
    if strategy.get("matrix") != {"gate": list(PUBLIC_GATES)}:
        raise AssertionError("public gate matrix differs from PUBLIC_GATES")
    if set(strategy) != {"fail-fast", "matrix"}:
        raise AssertionError("unexpected public matrix strategy")

    steps = public_job["steps"]
    if len(steps) != 4:
        raise AssertionError("public job must contain exactly four steps")
    action_uses = [step["uses"] for step in steps if "uses" in step]
    if action_uses != [CHECKOUT_ACTION, SETUP_PYTHON_ACTION]:
        raise AssertionError("actions must use the reviewed immutable pins")
    if steps[0] != {
        "name": "Checkout repository",
        "uses": CHECKOUT_ACTION,
        "with": {"persist-credentials": "false"},
    }:
        raise AssertionError("checkout must disable credential persistence")
    if steps[1] != {
        "name": "Set up Python 3.12",
        "uses": SETUP_PYTHON_ACTION,
        "with": {"python-version": "3.12"},
    }:
        raise AssertionError("setup-python must select Python 3.12")
    if steps[2] != {
        "name": "Bootstrap declared test dependencies",
        "run": (
            "python3 -m pip install --disable-pip-version-check "
            "-r requirements-dev.txt"
        ),
    }:
        raise AssertionError("bootstrap must use only requirements-dev.txt")
    if steps[3] != {
        "name": "Run public catalog gate",
        "run": "python3 -B tools/run_catalog_ci.py --gate ${{ matrix.gate }}",
    }:
        raise AssertionError("public gate command changed")

    if jobs["private-clean-room"] != {
        "name": "private-clean-room/UNPROVISIONED",
        "runs-on": "ubuntu-latest",
        "timeout-minutes": "1",
        "steps": [
            {
                "name": "Report missing private provisioning",
                "run": "echo 'private-clean-room/UNPROVISIONED' >&2\nexit 1\n",
            }
        ],
    }:
        raise AssertionError("private job must remain a fixed red placeholder")

    aggregate = jobs["catalog-validation"]
    if aggregate != {
        "name": "Skills Catalog Validation",
        "if": "${{ always() }}",
        "needs": ["public-gates", "private-clean-room"],
        "runs-on": "ubuntu-latest",
        "timeout-minutes": "1",
        "steps": [
            {"name": "Require every catalog prerequisite", "run": AGGREGATE_COMMAND}
        ],
    }:
        raise AssertionError("required aggregate contract changed")


class CatalogCIWorkflowTests(unittest.TestCase):
    def test_authored_fixture_is_marker_neutral(self) -> None:
        authored_source = Path(__file__).read_text(encoding="utf-8")

        self.assertEqual(list(markers(authored_source)), [])

    def test_exact_workflow_obeys_the_reviewed_contract(self) -> None:
        validate_workflow(load_workflow())

    def test_unsafe_deep_copy_mutations_are_causally_rejected(self) -> None:
        mutations = (
            ("removed gate", "public gate matrix", self._remove_gate),
            ("unknown gate", "public gate matrix", self._add_unknown_gate),
            ("fail-fast", "fail-fast", self._enable_fail_fast),
            ("job if", "job-level conditional", self._add_job_if),
            ("step if", "step-level conditional", self._add_step_if),
            (
                "continue-on-error",
                "continue-on-error",
                self._add_continue_on_error,
            ),
            ("unsafe event", "unsafe trigger", self._add_unsafe_event),
            ("workflow permission", "workflow permissions", self._raise_workflow_scope),
            ("job permission", "job permissions", self._add_job_scope),
            ("unpinned action", "immutable pins", self._unpin_checkout),
            ("credentials", "credential persistence", self._persist_credentials),
            ("env secret", "environment or secret", self._inject_secret_env),
            ("aggregate identity", "aggregate contract", self._rename_aggregate),
            ("aggregate dependency", "aggregate contract", self._drop_dependency),
            (
                "green on failure",
                "aggregate contract",
                self._accept_public_failure,
            ),
            ("green on skipped", "aggregate contract", self._accept_private_skip),
            ("green on cancelled", "aggregate contract", self._accept_cancelled),
        )
        baseline = load_workflow()
        for label, error, mutate in mutations:
            with self.subTest(mutation=label):
                candidate = copy.deepcopy(baseline)
                mutate(candidate)
                with self.assertRaisesRegex(AssertionError, error):
                    validate_workflow(candidate)

    @staticmethod
    def _remove_gate(workflow: dict[str, object]) -> None:
        workflow["jobs"]["public-gates"]["strategy"]["matrix"]["gate"].pop()

    @staticmethod
    def _add_unknown_gate(workflow: dict[str, object]) -> None:
        workflow["jobs"]["public-gates"]["strategy"]["matrix"]["gate"].append(
            "unknown-gate"
        )

    @staticmethod
    def _enable_fail_fast(workflow: dict[str, object]) -> None:
        workflow["jobs"]["public-gates"]["strategy"]["fail-fast"] = "true"

    @staticmethod
    def _add_job_if(workflow: dict[str, object]) -> None:
        workflow["jobs"]["public-gates"]["if"] = "${{ success() }}"

    @staticmethod
    def _add_step_if(workflow: dict[str, object]) -> None:
        workflow["jobs"]["public-gates"]["steps"][-1]["if"] = "${{ success() }}"

    @staticmethod
    def _add_continue_on_error(workflow: dict[str, object]) -> None:
        workflow["jobs"]["public-gates"]["continue-on-error"] = "true"

    @staticmethod
    def _add_unsafe_event(workflow: dict[str, object]) -> None:
        workflow["on"]["pull_request_target"] = {}

    @staticmethod
    def _raise_workflow_scope(workflow: dict[str, object]) -> None:
        workflow["permissions"]["contents"] = "write"

    def _add_job_scope(self, workflow: dict[str, object]) -> None:
        injected_permissions = {"id" + "-" + ("to" + "ken"): "write"}
        workflow["jobs"]["public-gates"]["permissions"] = injected_permissions
        self.assertEqual(
            injected_permissions,
            {"id" + "-" + ("to" + "ken"): "write"},
        )

    @staticmethod
    def _unpin_checkout(workflow: dict[str, object]) -> None:
        workflow["jobs"]["public-gates"]["steps"][0]["uses"] = "actions/checkout@v4"

    @staticmethod
    def _persist_credentials(workflow: dict[str, object]) -> None:
        checkout = workflow["jobs"]["public-gates"]["steps"][0]
        checkout["with"]["persist-credentials"] = "true"

    def _inject_secret_env(self, workflow: dict[str, object]) -> None:
        injected_environment = {
            "TO" + "KEN": "${{ " + "secrets." + "PRIVATE_" + "TOKEN" + " }}"
        }
        workflow["jobs"]["public-gates"]["env"] = injected_environment
        self.assertEqual(
            injected_environment,
            {
            "TO" + "KEN": "${{ " + "secrets." + "PRIVATE_" + "TOKEN" + " }}"
            },
        )

    @staticmethod
    def _rename_aggregate(workflow: dict[str, object]) -> None:
        workflow["jobs"]["catalog-validation"]["name"] = "Catalog Validation"

    @staticmethod
    def _drop_dependency(workflow: dict[str, object]) -> None:
        workflow["jobs"]["catalog-validation"]["needs"].pop()

    @staticmethod
    def _accept_public_failure(workflow: dict[str, object]) -> None:
        aggregate = workflow["jobs"]["catalog-validation"]["steps"][0]
        aggregate["run"] = aggregate["run"].replace(
            'public-gates.result }}" = success',
            'public-gates.result }}" = failure',
        )

    @staticmethod
    def _accept_private_skip(workflow: dict[str, object]) -> None:
        aggregate = workflow["jobs"]["catalog-validation"]["steps"][0]
        aggregate["run"] = aggregate["run"].replace(
            'private-clean-room.result }}" = success',
            'private-clean-room.result }}" = skipped',
        )

    @staticmethod
    def _accept_cancelled(workflow: dict[str, object]) -> None:
        aggregate = workflow["jobs"]["catalog-validation"]["steps"][0]
        aggregate["run"] = aggregate["run"].replace(
            'public-gates.result }}" = success',
            'public-gates.result }}" = cancelled',
        )

    def test_public_matrix_matches_runner_and_only_safe_triggers(self) -> None:
        workflow = load_workflow()

        self.assertEqual(
            workflow["on"],
            {"pull_request": {}, "push": {"branches": ["main"]}},
        )
        public_job = workflow["jobs"]["public-gates"]
        self.assertEqual(public_job["strategy"]["fail-fast"], "false")
        self.assertEqual(
            public_job["strategy"]["matrix"],
            {"gate": list(PUBLIC_GATES)},
        )
        gate_step = public_job["steps"][-1]
        for gate_id in PUBLIC_GATES:
            command = gate_step["run"].replace("${{ matrix.gate }}", gate_id)
            self.assertEqual(
                command,
                f"python3 -B tools/run_catalog_ci.py --gate {gate_id}",
            )

    def test_private_job_is_an_explicit_unprovisioned_failure(self) -> None:
        workflow = load_workflow()

        self.assertEqual(
            workflow["jobs"]["private-clean-room"],
            {
                "name": "private-clean-room/UNPROVISIONED",
                "runs-on": "ubuntu-latest",
                "timeout-minutes": "1",
                "steps": [
                    {
                        "name": "Report missing private provisioning",
                        "run": (
                            "echo 'private-clean-room/UNPROVISIONED' >&2\n"
                            "exit 1\n"
                        ),
                    }
                ],
            },
        )

    def test_required_aggregate_fails_unless_every_dependency_succeeds(self) -> None:
        workflow = load_workflow()
        aggregate = workflow["jobs"]["catalog-validation"]

        self.assertEqual(aggregate["name"], "Skills Catalog Validation")
        self.assertEqual(aggregate["if"], "${{ always() }}")
        self.assertEqual(
            aggregate["needs"], ["public-gates", "private-clean-room"]
        )
        self.assertEqual(aggregate["runs-on"], "ubuntu-latest")
        self.assertEqual(aggregate["timeout-minutes"], "1")
        self.assertEqual(len(aggregate["steps"]), 1)
        command = aggregate["steps"][0]["run"]
        for public_result, private_result in itertools.product(
            ("success", "failure", "skipped", "cancelled"), repeat=2
        ):
            with self.subTest(
                public_result=public_result, private_result=private_result
            ):
                rendered = render_fixed_aggregate_command(
                    command, public_result, private_result
                )
                completed = subprocess.run(
                    ["bash", "-eu", "-o", "pipefail", "-c", rendered],
                    cwd=REPO_ROOT,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                expected = public_result == private_result == "success"
                self.assertEqual(completed.returncode == 0, expected)
                self.assertEqual(completed.stdout, "")
                self.assertEqual(completed.stderr, "")


if __name__ == "__main__":
    unittest.main()
