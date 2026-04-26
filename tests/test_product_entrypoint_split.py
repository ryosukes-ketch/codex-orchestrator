from app.ai_work_system.main import create_app as create_ai_work_app
from app.macro_pulser.main import create_app as create_macro_split_app
from app.main import create_app as create_macro_compat_app


def test_macro_entrypoint_shim_remains_compatible_with_split_module() -> None:
    compat_app = create_macro_compat_app()
    split_app = create_macro_split_app()
    assert compat_app.title == "Macro Release Scanner v1.0"
    assert split_app.title == "Macro Release Scanner v1.0"


def test_ai_work_system_has_dedicated_entrypoint_package() -> None:
    app = create_ai_work_app()
    route_paths = {route.path for route in app.routes}
    assert app.title == "AI Work System Scaffold"
    assert "/health" in route_paths
    assert "/orchestrator/run" in route_paths
