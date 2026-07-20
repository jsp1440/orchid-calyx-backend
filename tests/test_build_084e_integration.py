from app.document_intelligence.models import DocumentClass
from app.document_intelligence.scientific import DisplayPolicy, IntelligenceStore

A=[{"revision_id":1,"page":1,"block_id":"methods-1","ordered_span":1},{"revision_id":1,"page":2,"block_id":"methods-2","ordered_span":2}]

def test_primary_research_end_to_end_protocol_and_result_coherence():
    s=IntelligenceStore(); s.register(1,{"title":"Materials and Methods Results statistical","display_policy":DisplayPolicy.FULL_TEXT_ALLOWED,"authors":["A"]},"paper")
    s.assess(1,peer_reviewed="YES",publication_type="JOURNAL_ARTICLE",citations_supplied="YES",citations_verified="YES")
    protocol=s.add_object("protocols",1,{"canonical_title":"Multi-page survey","complete_text":"method "*2000,"source_anchors":A,"retrieval_chunks":[{"span":1},{"span":2}],"linked_tables":[1],"linked_figures":[2],"supplements":[3]})
    result=s.add_object("results",1,{"research_question":"Does treatment work?","protocol_id":protocol["object_id"],"population":"plants","sample_size":40,"treatments":["treated"],"controls":["untreated"],"variables":["height"],"measurements":[{"value":12,"unit":"cm"}],"statistical_methods":["ANOVA"],"statistical_outputs":{"p":.01,"effect_size":.5,"uncertainty":"95% CI"},"tables":[1],"figures":[2],"caption":"Figure 1 complete caption","author_interpretation":"supported","limitations":["single site"],"discussion_links":[9],"source_anchors":A})
    assert s.classification(1)["document_class"]==DocumentClass.PRIMARY_RESEARCH
    assert len(s.complete("protocols",protocol["object_id"])["complete_text"])>10000
    assert s.complete("results",result["object_id"])["statistical_outputs"]["effect_size"]==.5

def test_representative_taxonomic_conservation_education_ai_intelligence_internal_fixtures():
    cases=[("taxonomic treatment identification key basionym",DocumentClass.TAXONOMIC_WORK),("recovery plan threat assessment conservation needs",DocumentClass.CONSERVATION_ASSESSMENT),("learning objectives lesson plan curriculum",DocumentClass.EDUCATIONAL_MATERIAL),("Kimi AI-generated citations",DocumentClass.AI_RESEARCH_SYNTHESIS),("Twin-AI grant deadline news monitoring",DocumentClass.INTELLIGENCE_REPORT),("BUILD-084 architecture roadmap",DocumentClass.INTERNAL_ORGANIZATIONAL)]
    for rid,(title,expected) in enumerate(cases,2):
        s=IntelligenceStore(); s.register(rid,{"title":title,"display_policy":DisplayPolicy.INTERNAL_RESEARCH_ONLY},title); assert s.classification(rid)["document_class"]==expected

def test_all_display_states_enforce_legal_policy_and_preview_limit():
    for n,policy in enumerate(DisplayPolicy,1):
        s=IntelligenceStore(); s.register(n,{"title":"report","display_policy":policy,"excerpt_limit":7,"license":"CC-BY","attribution_requirements":"cite issuer"},"protected text")
        p=s.add_object("protocols",n,{"complete_text":"protected text","source_anchors":[{"revision_id":n}]})
        public=s.complete("protocols",p["object_id"]); operator=s.complete("protocols",p["object_id"],authenticated=True)
        if policy==DisplayPolicy.FULL_TEXT_ALLOWED: assert public["complete_text"]=="protected text"
        elif policy==DisplayPolicy.INTERNAL_RESEARCH_ONLY: assert "complete_text" not in public and operator["complete_text"]=="protected text"
        else: assert "complete_text" not in public and "complete_text" not in operator
        if policy==DisplayPolicy.LIMITED_PREVIEW_ONLY: assert public["preview"]=="protect"
        assert public["license"]=="CC-BY" and public["attribution_requirements"]=="cite issuer"

def test_events_claims_taxon_links_and_adaptations_remain_unpublished_or_absent():
    s=IntelligenceStore(); s.register(1,{"title":"Twin-AI news monitoring","display_policy":DisplayPolicy.FULL_TEXT_ALLOWED})
    event=s.add_object("events",1,{"event_type":"NEWLY_DESCRIBED_SPECIES","event_date":"2026-07-01","reported_date":"2026-07-02","source":"report","verification_status":"UNVERIFIED","expiration":"2026-10-01","intended_consumers":["NEWS_AND_INTELLIGENCE"]})
    claim=s.add_object("claims",1,{"claim_type":"MACHINE_INFERENCE","claim_text":"candidate","source_anchors":[{"revision_id":1}],"verification_state":"UNVERIFIED"})
    assert event["published"] is claim["published"] is False
    assert "adapted_protocol" not in s.objects and "experiment" not in s.objects

def test_operator_routes_protect_every_mutation():
    from app.document_intelligence.routes import router
    mutations=[r for r in router.routes if getattr(r,"methods",set()) & {"POST","PUT","PATCH","DELETE"}]
    assert mutations
    assert all(any(getattr(d.call,"__name__","")=="verify_owner_or_api_key" for d in r.dependant.dependencies) for r in mutations)

def test_migration_only_targets_additive_document_intelligence_schema():
    from pathlib import Path
    sql=Path("migrations/084_document_intelligence.sql").read_text().upper()
    assert "DROP " not in sql and "TRUNCATE " not in sql
    assert "OC_GRAPH." not in sql and "OC_TAXONOMY." not in sql
    assert "CHECK(PUBLISHED=FALSE)" in sql and "CONFIGURATION_HASH" in sql
