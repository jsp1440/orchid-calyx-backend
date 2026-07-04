"""FastAPI router for Calyx Runtime v0.1."""
from fastapi import APIRouter

from .config_loader import BrainConfigLoader
from .infrastructure import InfrastructureRegistryService
from .scheduler import CalyxHeartbeat

router = APIRouter(prefix="/api/runtime", tags=["Calyx Runtime"])
config_router = APIRouter(prefix="/api/config", tags=["Calyx Config"])
infrastructure_router = APIRouter(prefix="/api/infrastructure", tags=["Calyx Infrastructure"])


@router.get("/heartbeat")
def runtime_heartbeat():
    return CalyxHeartbeat().run_once()


@router.get("/health")
def runtime_health():
    return {"runtime": CalyxHeartbeat().run_once()}


@config_router.get("/manifest")
def config_manifest():
    return BrainConfigLoader().load_manifest()


@config_router.get("/runtime-services")
def config_runtime_services():
    return BrainConfigLoader().load_runtime_services()


@config_router.get("/governance-policy")
def config_governance_policy():
    return BrainConfigLoader().load_governance_policy()


@config_router.get("/knowledge-preservation-policy")
def config_knowledge_preservation_policy():
    return BrainConfigLoader().load_knowledge_preservation_policy()


@infrastructure_router.get("/registry")
def infrastructure_registry():
    return InfrastructureRegistryService().registry()


@infrastructure_router.get("/health")
def infrastructure_health():
    return InfrastructureRegistryService().health()
