from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _line_numbers_with(text: str, needle: str) -> list[int]:
    return [idx for idx, line in enumerate(text.splitlines(), start=1) if needle in line]


def _has_legacy_context(text: str, line_no: int) -> bool:
    lines = text.splitlines()
    start = max(0, line_no - 6)
    end = min(len(lines), line_no + 2)
    context = "\n".join(lines[start:end]).lower()
    return "legacy compatibility alias" in context or "legacy compatibility aliases" in context


def test_legacy_macro_commands_are_only_documented_as_compatibility_aliases() -> None:
    targets = [
        ROOT / "README.md",
        ROOT / "docs" / "operational_startup_runbook.md",
        ROOT / "docs" / "operational_readiness_runbook.md",
    ]
    legacy_needles = [
        "python -m app.main api",
        ".\\scripts\\local-dev-smoke.ps1",
    ]

    for path in targets:
        text = path.read_text(encoding="utf-8")
        for needle in legacy_needles:
            for line_no in _line_numbers_with(text, needle):
                assert _has_legacy_context(text, line_no), (
                    f"{path} line {line_no} contains '{needle}' outside legacy compatibility context"
                )


def test_split_runtime_commands_remain_present_in_docs() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    startup = (ROOT / "docs" / "operational_startup_runbook.md").read_text(encoding="utf-8")
    readiness = (ROOT / "docs" / "operational_readiness_runbook.md").read_text(encoding="utf-8")

    assert ".\\scripts\\macro_pulser\\run-api.ps1" in readme
    assert ".\\scripts\\macro_pulser\\local-dev-smoke.ps1" in readme
    assert "python -m app.macro_pulser.main live --once --skip-remote-schedules" in readiness
    assert ".\\scripts\\macro_pulser\\run-api.ps1" in startup
    assert ".\\scripts\\macro_pulser\\local-dev-smoke.ps1" in startup
