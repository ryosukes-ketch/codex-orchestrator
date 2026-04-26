import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL_EXE = shutil.which("pwsh") or shutil.which("powershell")


def _run(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    assert POWERSHELL_EXE is not None
    command = [
        POWERSHELL_EXE,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(ROOT / "scripts" / script),
        *args,
    ]
    return subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_known_issues(path: Path, severity: str = "P2", status: str = "open") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "# Known Issues Register\n\n"
            "| Issue ID | Title | Severity | Status | Owner | First Seen (UTC) | Workaround | Next Action |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
            f"| KI-20260423-001 | Sample issue | {severity} | {status} | owner | 2026-04-23T00:00:00Z | manual workaround | monitor |\n"
        ),
        encoding="utf-8",
    )


def _prepare_release_train_inputs(tmp_path: Path, known_issue_severity: str, known_issue_status: str) -> dict:
    backlog_manifest = tmp_path / "post-launch-backlog-export.manifest.json"
    _write_json(
        backlog_manifest,
        {
            "bundle_type": "phase13_post_launch_release_backlog_package",
            "release_candidates": [
                {
                    "triage_id": "TRIAGE-001",
                    "category": "runbook",
                    "tier": "Medium",
                    "score": 8,
                    "backlog_lane": "next_release",
                    "route_rationale": "baseline candidate",
                }
            ],
            "runbook_patches": [],
            "monitoring_only": [],
            "deferred_items": [],
        },
    )

    readiness_summary = tmp_path / "readiness-summary.json"
    _write_json(readiness_summary, {"overall_status": "passed"})
    readiness_manifest = tmp_path / "readiness-manifest.json"
    _write_json(
        readiness_manifest,
        {
            "bundle_type": "readiness",
            "artifacts": {"readiness_summary": {"path": str(readiness_summary)}},
        },
    )

    known_issues_path = tmp_path / "known_issues_register.md"
    _write_known_issues(
        known_issues_path,
        severity=known_issue_severity,
        status=known_issue_status,
    )
    return {
        "backlog_manifest": backlog_manifest,
        "readiness_manifest": readiness_manifest,
        "known_issues_path": known_issues_path,
    }


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for release-train script tests.",
)
def test_phase14_release_train_pipeline_generates_evidence_package(tmp_path: Path) -> None:
    inputs = _prepare_release_train_inputs(tmp_path, known_issue_severity="P2", known_issue_status="open")
    candidate_manifest = tmp_path / "release-candidate.manifest.json"
    decision_manifest = tmp_path / "release-decision-package.manifest.json"
    notes_manifest = tmp_path / "release-notes.manifest.json"
    publication_manifest = tmp_path / "known-issue-publication.manifest.json"
    evidence_manifest = tmp_path / "release-train-evidence.manifest.json"

    candidate_result = _run(
        "release-candidate-promote.ps1",
        "-BacklogExportManifestPath",
        str(inputs["backlog_manifest"]),
        "-KnownIssuesPath",
        str(inputs["known_issues_path"]),
        "-OutPath",
        str(candidate_manifest),
        "-PromotionDocPath",
        str(tmp_path / "release_candidate_promotion.md"),
    )
    assert candidate_result.returncode == 0, candidate_result.stderr
    candidate_payload = json.loads(candidate_manifest.read_text(encoding="utf-8"))
    assert candidate_payload["bundle_type"] == "phase14_release_candidate_promotion"
    assert candidate_payload["rollout_recommendation"] == "go_candidate"

    decision_result = _run(
        "release-decision-package.ps1",
        "-ReleaseCandidateManifestPath",
        str(candidate_manifest),
        "-ReadinessManifestPath",
        str(inputs["readiness_manifest"]),
        "-OutPath",
        str(decision_manifest),
        "-DecisionDocPath",
        str(tmp_path / "release_go_hold_rollback_decision.md"),
    )
    assert decision_result.returncode == 0, decision_result.stderr
    decision_payload = json.loads(decision_manifest.read_text(encoding="utf-8"))
    assert decision_payload["bundle_type"] == "phase14_release_decision_package"
    assert decision_payload["decision"] == "GO"

    notes_result = _run(
        "release-notes-assemble.ps1",
        "-ReleaseCandidateManifestPath",
        str(candidate_manifest),
        "-ReleaseDecisionManifestPath",
        str(decision_manifest),
        "-KnownIssuesPath",
        str(inputs["known_issues_path"]),
        "-OutPath",
        str(notes_manifest),
        "-NotesDocPath",
        str(tmp_path / "release_note_publication_flow.md"),
    )
    assert notes_result.returncode == 0, notes_result.stderr
    notes_payload = json.loads(notes_manifest.read_text(encoding="utf-8"))
    assert notes_payload["bundle_type"] == "phase14_release_notes_assembly"
    assert Path(notes_payload["release_notes_markdown_path"]).exists()

    publication_result = _run(
        "known-issue-publication-route.ps1",
        "-KnownIssuesPath",
        str(inputs["known_issues_path"]),
        "-ReleaseDecisionManifestPath",
        str(decision_manifest),
        "-OutPath",
        str(publication_manifest),
    )
    assert publication_result.returncode == 0, publication_result.stderr
    publication_payload = json.loads(publication_manifest.read_text(encoding="utf-8"))
    assert publication_payload["bundle_type"] == "phase14_known_issue_publication_routing"
    assert publication_payload["routed_item_count"] == 1

    evidence_result = _run(
        "release-train-evidence-export.ps1",
        "-ReleaseCandidateManifestPath",
        str(candidate_manifest),
        "-ReleaseDecisionManifestPath",
        str(decision_manifest),
        "-ReleaseNotesManifestPath",
        str(notes_manifest),
        "-KnownIssuePublicationManifestPath",
        str(publication_manifest),
        "-OutPath",
        str(evidence_manifest),
        "-EvidenceDocPath",
        str(tmp_path / "release_train_evidence_flow.md"),
    )
    assert evidence_result.returncode == 0, evidence_result.stderr
    evidence_payload = json.loads(evidence_manifest.read_text(encoding="utf-8"))
    assert evidence_payload["bundle_type"] == "phase14_release_train_evidence"
    assert evidence_payload["summary"]["decision"] == "GO"


@pytest.mark.skipif(os.name != "nt", reason="PowerShell script contracts are Windows-only.")
@pytest.mark.skipif(
    POWERSHELL_EXE is None,
    reason="PowerShell is required for release-train script tests.",
)
def test_phase14_release_decision_package_requires_rollback_for_open_p0_issue(
    tmp_path: Path,
) -> None:
    inputs = _prepare_release_train_inputs(tmp_path, known_issue_severity="P0", known_issue_status="open")
    candidate_manifest = tmp_path / "release-candidate.manifest.json"
    decision_manifest = tmp_path / "release-decision-package.manifest.json"

    candidate_result = _run(
        "release-candidate-promote.ps1",
        "-BacklogExportManifestPath",
        str(inputs["backlog_manifest"]),
        "-KnownIssuesPath",
        str(inputs["known_issues_path"]),
        "-OutPath",
        str(candidate_manifest),
        "-PromotionDocPath",
        str(tmp_path / "release_candidate_promotion.md"),
    )
    assert candidate_result.returncode == 0, candidate_result.stderr
    candidate_payload = json.loads(candidate_manifest.read_text(encoding="utf-8"))
    assert "open P0 known issue present" in candidate_payload["hold_reasons"]

    decision_result = _run(
        "release-decision-package.ps1",
        "-ReleaseCandidateManifestPath",
        str(candidate_manifest),
        "-ReadinessManifestPath",
        str(inputs["readiness_manifest"]),
        "-OutPath",
        str(decision_manifest),
        "-DecisionDocPath",
        str(tmp_path / "release_go_hold_rollback_decision.md"),
    )
    assert decision_result.returncode == 0, decision_result.stderr
    decision_payload = json.loads(decision_manifest.read_text(encoding="utf-8"))
    assert decision_payload["decision"] == "ROLLBACK_REQUIRED"
    assert decision_payload["rollback_signal"] == "rollback_required"
