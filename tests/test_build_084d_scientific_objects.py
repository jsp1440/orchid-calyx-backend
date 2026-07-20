from app.document_intelligence.classifier import classify
from app.document_intelligence.models import DocumentClass
from app.document_intelligence.scientific import IntelligenceStore, DisplayPolicy

ANCHOR=[{"revision_id":1,"page":1,"block_id":"b1","ordered_span":1}]

def store(policy=DisplayPolicy.FULL_TEXT_ALLOWED):
    s=IntelligenceStore(); s.register(1,{"title":"Materials and Methods Results statistical","display_policy":policy},"complete evidence text"); return s

def test_all_top_level_classes_are_representable_and_ruleset_persisted():
    samples={"materials and methods results statistical":DocumentClass.PRIMARY_RESEARCH,"systematic review":DocumentClass.REVIEW_SYNTHESIS,"taxonomic treatment":DocumentClass.TAXONOMIC_WORK,"chapter isbn":DocumentClass.BOOK_OR_CHAPTER,"recovery plan":DocumentClass.CONSERVATION_ASSESSMENT,"technical report":DocumentClass.TECHNICAL_REPORT,"learning objectives":DocumentClass.EDUCATIONAL_MATERIAL,"Kimi AI-generated":DocumentClass.AI_RESEARCH_SYNTHESIS,"Twin-AI grant deadline":DocumentClass.INTELLIGENCE_REPORT,"BUILD-084 architecture":DocumentClass.INTERNAL_ORGANIZATIONAL,"supplementary dataset":DocumentClass.DATASET_OR_SUPPLEMENT,"unmatched":DocumentClass.OTHER}
    for text,expected in samples.items():
        result=classify(text,text); assert result.document_class==expected and result.version

def test_low_confidence_review_and_audited_override_do_not_mutate_revision():
    s=IntelligenceStore(); before=s.register(7,{"title":"unknown","display_policy":DisplayPolicy.FULL_TEXT_ALLOWED}); s.override_classification(7,"TECHNICAL_REPORT","operator evidence","alice")
    assert s.records[7]==before and any(r["category"]=="UNCERTAIN_CLASSIFICATION" for r in s.reviews.values())
    assert s.audit[-1]["action"]=="CLASSIFICATION_OVERRIDE"

def test_multidimensional_reliability_has_no_truth_score():
    s=store(); a=s.assess(1,peer_reviewed="NO",ai_generated="YES",human_reviewed="YES",citations_verified="PARTIAL",authority_category="INSTITUTIONAL",evidence_tier="AUTHORITATIVE_REPORT",temporal_status="TIME_SENSITIVE",review_after="2027-01-01",reliability_assessment={"methods":"weak","issuer":"authoritative"})
    assert a["peer_reviewed"]=="NO" and a["ai_generated"]=="YES" and "truth_score" not in a

def test_consumers_protocol_result_and_retrieval_are_complete():
    s=store(); s.assign_consumer(1,"RESEARCH_PLATFORM",.9,"methods evidence"); s.assign_consumer(1,"CONSERVATION_PLATFORM",.7,"application")
    p=s.add_object("protocols",1,{"canonical_title":"Survey","complete_text":"A"*2000,"ordered_steps":["one","two"],"source_anchors":ANCHOR,"linked_tables":[4],"linked_figures":[5],"parent_canonical_protocol_id":None})
    r=s.add_object("results",1,{"research_question":"Q","protocol_id":p["object_id"],"sample_size":12,"controls":["control"],"measurements":[{"value":2,"unit":"cm"}],"statistics":{"effect_size":.4},"components":["figure","table","caption","interpretation"],"source_anchors":ANCHOR})
    assert len(s.complete("protocols",p["object_id"])["complete_text"])==2000
    assert s.complete("results",r["object_id"])["protocol_id"]==p["object_id"] and len(s.consumers)==2

def test_taxonomic_presentation_and_key_branching():
    s=store(); t=s.add_object("treatments",1,{"accepted_name":"Orchis originalis Author","ordered_sections":["synonymy","diagnosis","description","specimens"],"candidate_links":[],"source_anchors":ANCHOR})
    k=s.add_object("keys",1,{"title":"Key","original_wording":"1a Leaves... Taxon A","nodes":[{"couplet":"1","lead":"a","target":"Taxon A"},{"couplet":"1","lead":"b","target_node_id":2}],"source_anchors":ANCHOR})
    assert s.complete("treatments",t["object_id"])["ordered_sections"][0]=="synonymy" and len(s.complete("keys",k["object_id"])["nodes"])==2

def test_insights_events_claim_distinctions_never_publish():
    s=store(); insight=s.add_object("insights",1,{"category":"recommendation","directly_stated":False,"document_class":"AI_RESEARCH_SYNTHESIS","verification_status":"UNVERIFIED","source_anchors":ANCHOR})
    event=s.add_object("events",1,{"event_type":"GRANT_ANNOUNCEMENT","verification_status":"UNVERIFIED","expiration_date":"2027-01-01"})
    fact=s.add_object("claims",1,{"claim_type":"DIRECTLY_STATED_FACT","claim_text":"x","contradiction_status":"NONE","source_anchors":ANCHOR}); inference=s.add_object("claims",1,{"claim_type":"MACHINE_INFERENCE","claim_text":"y","contradiction_status":"CANDIDATE","source_anchors":ANCHOR})
    assert not any(x["published"] for x in (insight,event,fact,inference)) and fact["claim_type"]!=inference["claim_type"]

def test_review_resolution_audit_and_conservative_display():
    s=IntelligenceStore(); s.register(1,{"title":"report","display_policy":DisplayPolicy.UNKNOWN_REQUIRES_REVIEW},"secret full text"); item=next(iter(s.reviews.values())); s.resolve_review(item["review_id"],"METADATA_ONLY","license absent","alice")
    p=s.add_object("protocols",1,{"canonical_title":"Restricted","complete_text":"secret full text","source_anchors":ANCHOR})
    assert "complete_text" not in s.complete("protocols",p["object_id"],authenticated=True)
    assert s.audit[-1]["action"]=="REVIEW_RESOLVED"

def test_full_text_policy_and_internal_policy_are_independent_of_api_key():
    full=store(DisplayPolicy.FULL_TEXT_ALLOWED); p=full.add_object("protocols",1,{"complete_text":"allowed","source_anchors":ANCHOR}); assert full.complete("protocols",p["object_id"])["complete_text"]=="allowed"
    restricted=store(DisplayPolicy.METADATA_ONLY); q=restricted.add_object("protocols",1,{"complete_text":"restricted","source_anchors":ANCHOR}); assert "complete_text" not in restricted.complete("protocols",q["object_id"],authenticated=True)

def test_safety_contract_has_no_drive_write_graph_publish_or_embeddings():
    from pathlib import Path
    text="\n".join(p.read_text() for p in Path("app/document_intelligence").glob("*.py"))
    assert all(term not in text for term in ("drive.files.update","drive.files.delete","production_publish","create_embedding"))
