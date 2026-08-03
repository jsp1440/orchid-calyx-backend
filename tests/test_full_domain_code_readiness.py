from runtime.knowledge_graph.full_domain_status import full_domain_code_readiness


def test_every_production_domain_has_an_adapter():
    report = full_domain_code_readiness()
    production = [d for d in report["domains"] if d["configured_status"] == "production"]
    assert production
    assert all(d["adapter_registered"] for d in production)


def test_unregistered_source_projections_are_explicit_blockers():
    report = full_domain_code_readiness()
    for domain in report["domains"]:
        if domain["configured_status"] != "production":
            continue
        if not domain["source_projection_enabled"]:
            assert domain["limitation"]
            assert any(item.startswith(f"{domain['domain']}:") for item in report["blockers"])
