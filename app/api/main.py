from fastapi import FastAPI

from app.api.dependencies import clear_auth_service_dependency_caches
from app.api.routes import router
from app.api.runtime_bindings import bind_auth_service_binding, bind_orchestrator_binding
from app.orchestrator.service import PMOrchestrator
from app.services.auth import get_auth_service


def create_app() -> FastAPI:
    clear_auth_service_dependency_caches()
    app = FastAPI(title="AI Work System Scaffold", version="0.1.0")
    runtime_orchestrator = PMOrchestrator()
    auth_service = get_auth_service()
    bind_orchestrator_binding(app, orchestrator=runtime_orchestrator)
    bind_auth_service_binding(app, auth_service=auth_service)
    app.include_router(router)
    return app


app = create_app()
