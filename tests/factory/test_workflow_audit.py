from pathlib import Path

from tools.workflow_audit import audit_workflow


def test_workflow_audit_flags_dispatch_input_and_step_output_in_multiline_run(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yml"
    workflow.write_text(
        """name: test
on: workflow_dispatch
permissions:
  contents: read
jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - name: unsafe
        env:
          PLAN_ID: ${{ inputs.plan_id }}
          RESOLVED: ${{ steps.resolve.outputs.plan_id }}
        run: |
          echo \"${{ inputs.plan_id }}\"
          echo \"${{ steps.resolve.outputs.plan_id }}\"
""",
        encoding="utf-8",
    )

    findings = audit_workflow(workflow)

    assert [finding["kind"] for finding in findings] == ["input-in-shell", "input-in-shell"]


def test_workflow_audit_allows_expression_in_env_and_shell_variable_use(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yml"
    workflow.write_text(
        """name: test
on: workflow_dispatch
permissions:
  contents: read
jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - name: safe
        env:
          PLAN_ID: ${{ inputs.plan_id }}
        run: |
          python -m factory.cli plan --plan-id \"$PLAN_ID\"
""",
        encoding="utf-8",
    )

    assert audit_workflow(workflow) == []


def test_run_parser_checks_inline_run_commands_too(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yml"
    workflow.write_text(
        """name: test
on: workflow_dispatch
permissions:
  contents: read
jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - name: unsafe inline command
        run: echo \"${{ inputs.plan_id }}\"
""",
        encoding="utf-8",
    )

    findings = audit_workflow(workflow)

    assert len(findings) == 1
    assert findings[0]["kind"] == "input-in-shell"


def test_production_pause_check_runs_before_dependencies_and_rendering() -> None:
    workflow = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "produce.yml"
    text = workflow.read_text(encoding="utf-8")

    assert text.index("- name: Emergency stop check") < text.index("- name: Set up Python")
    assert text.index("- name: Emergency stop check") < text.index("- name: Resume or render")
