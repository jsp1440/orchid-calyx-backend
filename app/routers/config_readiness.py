"""Owner-only Release 1 configuration readiness (presence booleans only)."""

from fastapi import APIRouter, Depends

from app.member_auth import owner_session_only
from app.release_env import config_readiness

# Owner session only: the backend API key is a service credential, a member is
# 403 and an anonymous caller is 401. The response names variables and says
# whether each is present and required; it never carries a value.
router = APIRouter(
    prefix="/api/system",
    tags=["system"],
    dependencies=[Depends(owner_session_only)],
)


@router.get("/config-readiness")
def get_config_readiness() -> dict[str, object]:
    return config_readiness()
