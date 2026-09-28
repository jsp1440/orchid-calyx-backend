"""A one-task live authorization must not enable the rest of the provider queue."""

import pytest

from app.literature_extraction import firecrawl_runtime as runtime
from app.literature_extraction.firecrawl_provider import AcquisitionBlocked


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["", "124"])
async def test_live_pilot_requires_exact_issue_scope(monkeypatch, scope):
    monkeypatch.setenv("FIRECRAWL_ENABLED", "true")
    monkeypatch.setenv("FIRECRAWL_DRY_RUN", "false")
    monkeypatch.setenv("FIRECRAWL_PILOT_MODE", "true")
    monkeypatch.setenv("FIRECRAWL_PILOT_ISSUE_NUMBER", scope)
    monkeypatch.setattr(
        runtime,
        "verify_swarm_acquisition_lease",
        lambda **_: {
            "body": "OC-ACQUISITION-GENUS: Paphiopedilum",
        },
    )

    class NoProvider:
        def __init__(self, *args, **kwargs):
            raise AssertionError("out-of-scope task must never instantiate provider")

    monkeypatch.setattr(runtime, "FirecrawlProvider", NoProvider)
    request = runtime.AcquisitionRequest(
        issue_number=123, run_id=77, run_attempt=1, comment_id=100
    )
    with pytest.raises(AcquisitionBlocked, match="LIVE_PILOT_ISSUE_SCOPE_REQUIRED"):
        await runtime.execute_acquisition(request, github=object())
