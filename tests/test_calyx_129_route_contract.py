from runtime.calyx_certification.route_contract import build_route_contract_snapshot


def test_complete_route_contract_builds_hash():
    result = build_route_contract_snapshot(
        [
            {
                "method": "GET",
                "path": "/api/calyx/status",
                "auth_required": True,
                "response_schema": "CertificationStatus",
            }
        ]
    )
    assert result["route_contract_ready"] is True
    assert len(result["route_contract_hash"]) == 64


def test_empty_contract_blocks():
    assert build_route_contract_snapshot([])["route_contract_ready"] is False
