from __future__ import annotations

from fastapi import APIRouter, Depends

from app.security import verify_owner_or_api_key

from .models import CertificationReport, CertificationTarget
from .service import ApplicationCertificationService, EDITH_TARGET

router = APIRouter(
    prefix="/api/application-certification",
    tags=["application-certification"],
    dependencies=[Depends(verify_owner_or_api_key)],
)


def get_service() -> ApplicationCertificationService:
    return ApplicationCertificationService()


@router.get("/targets/edith-bramble", response_model=CertificationTarget)
def edith_target() -> CertificationTarget:
    return EDITH_TARGET


@router.post("/certify", response_model=CertificationReport)
def certify(
    target: CertificationTarget,
    service: ApplicationCertificationService = Depends(get_service),
) -> CertificationReport:
    return service.certify(target)


@router.post("/targets/edith-bramble/run", response_model=CertificationReport)
def certify_edith(
    service: ApplicationCertificationService = Depends(get_service),
) -> CertificationReport:
    return service.certify(EDITH_TARGET)
