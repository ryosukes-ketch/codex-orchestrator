import app.agents as agents_pkg
import app.intake as intake_pkg
import app.orchestrator as orchestrator_pkg
import app.providers as providers_pkg
import app.schemas as schemas_pkg
import app.services as services_pkg
import app.state as state_pkg
from app.agents.departments import (
    BuildAgent,
    DesignAgent,
    ResearchAgent,
    ReviewAgent,
    TrendAgent,
)
from app.intake.review_artifacts import (
    current_brief_to_management_review_input,
    intake_result_to_current_brief_artifact,
)
from app.intake.service import IntakeAgent
from app.orchestrator.service import PMOrchestrator
from app.providers.factory import get_trend_provider
from app.schemas.management import (
    ManagementReviewInput,
    ManagementReviewPacket,
    ManagementReviewSummary,
)
from app.schemas.management_decision import ManagementDecisionRecord
from app.services.auth import get_auth_service
from app.services.dry_run_orchestration import run_dry_run_orchestration
from app.state.repository import (
    InMemoryProjectRepository,
    PostgresProjectRepository,
    ProjectRepository,
    create_repository_from_env,
)


def test_agents_package_reexports_department_agents() -> None:
    assert agents_pkg.ResearchAgent is ResearchAgent
    assert agents_pkg.DesignAgent is DesignAgent
    assert agents_pkg.BuildAgent is BuildAgent
    assert agents_pkg.ReviewAgent is ReviewAgent
    assert agents_pkg.TrendAgent is TrendAgent


def test_intake_package_reexports_helpers_and_agent() -> None:
    assert intake_pkg.IntakeAgent is IntakeAgent
    assert (
        intake_pkg.intake_result_to_current_brief_artifact
        is intake_result_to_current_brief_artifact
    )
    assert (
        intake_pkg.current_brief_to_management_review_input
        is current_brief_to_management_review_input
    )


def test_orchestrator_package_reexports_pm_orchestrator() -> None:
    assert orchestrator_pkg.PMOrchestrator is PMOrchestrator


def test_providers_package_reexports_factory_function() -> None:
    assert providers_pkg.get_trend_provider is get_trend_provider


def test_state_package_reexports_repository_symbols() -> None:
    assert state_pkg.ProjectRepository is ProjectRepository
    assert state_pkg.InMemoryProjectRepository is InMemoryProjectRepository
    assert state_pkg.PostgresProjectRepository is PostgresProjectRepository
    assert state_pkg.create_repository_from_env is create_repository_from_env


def test_services_package_reexports_stable_entrypoints() -> None:
    assert services_pkg.get_auth_service is get_auth_service
    assert services_pkg.run_dry_run_orchestration is run_dry_run_orchestration


def test_schemas_package_reexports_management_shapes() -> None:
    assert schemas_pkg.ManagementDecisionRecord is ManagementDecisionRecord
    assert schemas_pkg.ManagementReviewInput is ManagementReviewInput
    assert schemas_pkg.ManagementReviewSummary is ManagementReviewSummary
    assert schemas_pkg.ManagementReviewPacket is ManagementReviewPacket
