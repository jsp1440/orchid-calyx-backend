"""Provider webhook endpoint for the society CRM payment ledger.

``POST /api/society/webhooks/stripe`` is authenticated by the ``Stripe-Signature``
header (HMAC with ``OC_STRIPE_WEBHOOK_SECRET``), not by a user session:

* 400 -- missing/malformed/expired/non-matching signature; nothing is written;
* 200 -- processed, duplicate (redelivery), ignored (unsupported type), unroutable,
  or a recorded non-retryable failure (visible in admin diagnostics);
* 503 -- webhook secret not configured, or a recorded failure that a redelivery can
  fix (e.g. a refund that arrived before its payment), so Stripe retries.

The raw body is read unmodified because the signature covers the exact bytes.
Nothing from the payload or the secret is logged.

Like the rest of the society CRM API it answers 503 until
``OC_SOCIETY_CRM_API_ENABLED`` is set. Authenticated administrator payment endpoints
live in ``society_data_routes``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from .payments import (
    MAX_WEBHOOK_PAYLOAD_BYTES,
    PaymentLedgerService,
    PaymentProvider,
    StripeWebhookAdapter,
    WebhookSignatureError,
)
from .postgres_repository import PostgresSocietyCRMRepository
from .society_routes import require_enabled
from .society_service import SocietyCRMService


@lru_cache(maxsize=1)
def _default_service() -> PaymentLedgerService:
    repo = PostgresSocietyCRMRepository()
    return PaymentLedgerService(repo, SocietyCRMService(repo))


def build_payment_webhook_router(
    *,
    service_factory: Callable[[], PaymentLedgerService] = _default_service,
    adapter_factory: Callable[[], PaymentProvider] = StripeWebhookAdapter.from_env,
    clock: Callable[[], float] = time.time,
) -> APIRouter:
    webhook_router = APIRouter(
        prefix="/api/society/webhooks", tags=["society-crm-payments"], dependencies=[Depends(require_enabled)]
    )

    @webhook_router.post("/stripe")
    async def stripe_webhook(request: Request) -> JSONResponse:
        try:
            adapter = adapter_factory()
        except ValueError:
            raise HTTPException(status_code=503, detail="WEBHOOK_NOT_CONFIGURED") from None
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_WEBHOOK_PAYLOAD_BYTES:
            raise HTTPException(status_code=413, detail="WEBHOOK_PAYLOAD_TOO_LARGE")
        payload = await request.body()
        signature = request.headers.get("stripe-signature")
        service = service_factory()
        try:
            result = await run_in_threadpool(service.handle_webhook, adapter, payload, signature, clock())
        except WebhookSignatureError as exc:
            raise HTTPException(status_code=400, detail=exc.code) from None
        body = {key: result.get(key) for key in (
            "status", "provider_event_id", "event_type", "error_code", "retryable", "payment_id")}
        status_code = 503 if result.get("status") == "failed" and result.get("retryable") else 200
        return JSONResponse(body, status_code=status_code)

    return webhook_router


router = build_payment_webhook_router()

__all__ = ["build_payment_webhook_router", "router"]
