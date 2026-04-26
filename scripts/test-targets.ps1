function Get-OperationalPytestTargets {
    return @(
        "tests/test_api.py",
        "tests/test_orchestrator.py",
        "tests/test_dry_run_orchestration.py",
        "tests/test_sqlite_repository.py",
        "tests/test_repository_factory.py",
        "tests/test_operator_workflow_contract.py",
        "tests/test_operator_scripts_e2e.py",
        "tests/test_sqlite_ops_scripts.py",
        "tests/test_sqlite_export_script.py",
        "tests/test_operator_replay_export_script.py",
        "tests/test_operator_support_bundle_script.py",
        "tests/test_operator_stage_gate_script.py",
        "tests/test_openclaw_gateway_evidence_scripts.py"
    )
}
