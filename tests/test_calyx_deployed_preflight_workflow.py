from pathlib import Path


def test_deployed_preflight_uses_public_variable_and_private_secret():
    workflow = Path(".github/workflows/calyx-deployed-preflight-smoke.yml").read_text()
    assert "CALYX_BACKEND_URL: ${{ vars.CALYX_BACKEND_URL }}" in workflow
    assert "CALYX_OWNER_ACCESS_CODE: ${{ secrets.CALYX_OWNER_ACCESS_CODE }}" in workflow
    assert "Repository variable CALYX_BACKEND_URL is required" in workflow
    assert "Repository secret CALYX_OWNER_ACCESS_CODE is required" in workflow
