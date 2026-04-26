from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_macro_pulser_script_entrypoints_exist_and_target_split_runtime() -> None:
    required = [
        "scripts/macro_pulser/run-api.ps1",
        "scripts/macro_pulser/run-live.ps1",
        "scripts/macro_pulser/run-backfill.ps1",
        "scripts/macro_pulser/run-replay.ps1",
        "scripts/macro_pulser/local-dev-smoke.ps1",
    ]
    for rel in required:
        assert (ROOT / rel).exists(), rel

    assert "app.macro_pulser.main" in _read("scripts/macro_pulser/run-api.ps1")
    assert "app.macro_pulser.main" in _read("scripts/macro_pulser/run-live.ps1")
    assert "app.macro_pulser.main" in _read("scripts/macro_pulser/run-backfill.ps1")
    assert "app.macro_pulser.main" in _read("scripts/macro_pulser/run-replay.ps1")
    assert "scripts\\local-dev-smoke.ps1" in _read("scripts/macro_pulser/local-dev-smoke.ps1")


def test_legacy_macro_pulser_root_scripts_keep_migration_notice() -> None:
    for rel in (
        "scripts/run_live.sh",
        "scripts/run_backfill.sh",
        "scripts/run_replay.sh",
        "scripts/local-dev-smoke.ps1",
    ):
        assert (ROOT / rel).exists(), rel

    assert "Legacy compatibility entrypoint for MacroPulser." in _read("scripts/run_live.sh")
    assert "scripts/macro_pulser/run-live.ps1" in _read("scripts/run_live.sh")
    assert "Legacy compatibility entrypoint for MacroPulser." in _read("scripts/run_backfill.sh")
    assert "scripts/macro_pulser/run-backfill.ps1" in _read("scripts/run_backfill.sh")
    assert "Legacy compatibility entrypoint for MacroPulser." in _read("scripts/run_replay.sh")
    assert "scripts/macro_pulser/run-replay.ps1" in _read("scripts/run_replay.sh")
    assert "Legacy compatibility entrypoint for MacroPulser local smoke." in _read("scripts/local-dev-smoke.ps1")
    assert "scripts\\macro_pulser\\local-dev-smoke.ps1" in _read("scripts/local-dev-smoke.ps1")


def test_ai_work_system_script_entrypoints_exist_and_forward_to_current_root_contract() -> None:
    required = [
        "scripts/ai_work_system/start-server.ps1",
        "scripts/ai_work_system/release-readiness.ps1",
        "scripts/ai_work_system/operator-menu.ps1",
    ]
    for rel in required:
        assert (ROOT / rel).exists(), rel

    assert "scripts\\start-server.ps1" in _read("scripts/ai_work_system/start-server.ps1")
    assert "scripts\\release-readiness.ps1" in _read("scripts/ai_work_system/release-readiness.ps1")
    assert "scripts\\operator-menu.ps1" in _read("scripts/ai_work_system/operator-menu.ps1")
