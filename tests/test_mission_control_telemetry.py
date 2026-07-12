from fastapi import FastAPI

from app.routers.health import router
from app.routers.mission_control import mission_control_health, mission_control_runtime


def test_mission_control_expected_frontend_endpoints_are_mounted():
    app = FastAPI()
    app.include_router(router)

    expected_endpoints = [
        "/api/mission-control/subsystems",
        "/api/mission-control/health",
        "/api/mission-control/builds",
        "/api/mission-control/harvesters",
        "/api/mission-control/runtime",
        "/api/mission-control/governance",
        "/api/mission-control/recommendations",
    ]
    mounted_paths = {route.path for route in app.routes}

    for endpoint in expected_endpoints:
        assert endpoint in mounted_paths


def test_mission_control_health_is_read_only_telemetry():
    data = mission_control_health()
    assert data["safety"]["read_only"] is True
    assert data["safety"]["write_controls_enabled"] is False
    assert data["build"] == "BUILD-065"
    assert data["id"] == "mission_control_backend"
    assert data["telemetry_source"] == "orchid-calyx-backend read-only telemetry router"


def test_mission_control_runtime_does_not_expose_operations():
    runtime = mission_control_runtime()["runtime"]
    assert runtime["id"] == "calyx_runtime"
    assert runtime["safety"]["read_only"] is True
    assert runtime["safety"]["deploy_controls_enabled"] is False
    assert runtime["safety"]["pause_resume_enabled"] is False
