from functools import lru_cache

from .repositories import PostgresMissionRepository
from .services import MissionService


@lru_cache(maxsize=1)
def get_mission_repository() -> PostgresMissionRepository:
    return PostgresMissionRepository()


def get_mission_service() -> MissionService:
    return MissionService(get_mission_repository())
