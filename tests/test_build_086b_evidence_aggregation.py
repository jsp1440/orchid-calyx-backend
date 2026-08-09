from pathlib import Path
from app.evidence_aggregation.models import AggregateType,CandidateInput,ConsensusStatus,EvidenceRelationship
from app.evidence_aggregation.repository import MemoryAggregateRepository
from app.evidence_aggregation.service import EvidenceAggregationService

def c(i,value="bee",**kw):
 data={"candidate_id":i,"candidate_version":1,"candidate_type":"POLLINATOR_ASSOCIATION","normalized_subject":"Dracula vampira","predicate":"pollinated_by","object_value":value,"source_revision_id":i,"source_document_id":f"doc-{i}","source_anchor_ids":(i*10,),"source_class":"PRIMARY","evidence_type":"DIRECT_OBSERVATION","directness":"DIRECT_OBSERVATION","source_lineage":f"study-{i}","document_hash":f"hash-{i}","confidence":.8,"display_policy":"FULL_TEXT_ALLOWED"}; data.update(kw); return CandidateInput(**data)
def setup():r=MemoryAggregateRepository();return r,EvidenceAggregationService(r)
def execute(items):r,s=setup();p=s.preview(items);s.execute(p["aggregate_run_id"]);return r,s,p

def test_migration_models_types_and_protected_schema_safety():
 sql=Path("migrations/086b_evidence_aggregation.sql").read_text().upper(); assert "OC_CANDIDATE_KNOWLEDGE.CANDIDATES" in sql and "OC_DOCUMENT_INTELLIGENCE.SOURCE_ANCHORS" in sql and "AGGREGATE_VERSIONS" in sql and "AGGREGATE_TOMBSTONES" in sql
 assert "PUBLISHED BOOLEAN NOT NULL DEFAULT FALSE CHECK(PUBLISHED=FALSE)" in sql and len(AggregateType)==21
 assert AggregateType.MECHANISTIC_RELATIONSHIP_AGGREGATE.value == "MECHANISTIC_RELATIONSHIP_AGGREGATE"
 assert all(x not in sql for x in ("DROP ","TRUNCATE ","OC_GRAPH.","OC_TAXONOMY."))

def test_preview_persists_plan_without_aggregate_mutation():
 r,s=setup();p=s.preview([c(1),c(2)]);assert p["state"]=="PLANNED" and p["aggregates_created"]==0 and not r.clusters and not r.versions and p["candidate_versions"]==["1:1","2:1"]

def test_independence_derivatives_duplicates_and_support_do_not_inflate_counts():
 items=[c(1),c(2),c(3,source_class="REVIEW",source_lineage="study-1",citation_lineage=("study-1","study-2")),c(4,source_class="AI_SYNTHESIS",source_lineage="study-1"),c(5,document_hash="hash-1",source_lineage="study-1")];r,_,_=execute(items);a=r.versions[0]
 assert a["source_count"]==2 and a["confidence_dimensions"]["derivative_sources"]==3 and a["duplicate_evidence_count"]>=1 and len(a["contributing_candidate_ids"])==5

def test_explicit_conflict_visible_without_automatic_winner():
 r,_,_=execute([c(1),c(2,"moth",metadata={"relationship_to":{"1":"CONTRADICTS"}})]);a=r.versions[0]
 assert a["aggregate_status"]==ConsensusStatus.CONFLICTING and a["contradictory_evidence_count"]==1 and r.conflicts and len(a["contributing_candidate_ids"])==2

def test_context_prevents_false_contradiction_and_geography_is_not_universalized():
 a=c(1,"January",candidate_type="PHENOLOGY_EVENT",predicate="flowers_in",geographic_context={"region":"Ecuador"},temporal_context={"season":"wet"});b=c(2,"July",candidate_type="PHENOLOGY_EVENT",predicate="flowers_in",geographic_context={"region":"Peru"},temporal_context={"season":"dry"});r,_,_=execute([a,b]);assert len(r.versions)==2 and all(not x["geographic_context"]["universalized"] for x in r.versions)
 m1=c(3,"high",candidate_type="TRAIT",predicate="tolerance",method_context={"class":"acute"});m2=c(4,"low",candidate_type="TRAIT",predicate="tolerance",method_context={"class":"chronic"});r,_,_=execute([m1,m2]);assert any(x["relationship_type"]==EvidenceRelationship.METHOD_DEPENDENT for x in r.relationships) and not any(x["relationship_type"]=="CONTRADICTS" for x in r.relationships)

def test_taxonomy_temporal_and_historical_source_usage_are_preserved():
 links=({"candidate_taxon_id":11,"source_name":"Old name","confidence":.7},{"candidate_taxon_id":12,"source_name":"Other concept","confidence":.5});old=c(1,candidate_type="TAXON_NAME_USAGE",taxon_links=links,metadata={"source_name":"Historical name"},status="SUPERSEDED",temporal_context={"observation_date":"1900-01-01"});r,_,_=execute([old]);a=r.versions[0]
 assert a["taxonomic_context"]["source_names"]==["Historical name"] and not a["taxonomic_context"]["canonical_rewrite_performed"] and a["taxonomic_context"]["ambiguous_candidate_ids"]==[1]
 assert a["temporal_context"]["trend_conclusion"] is None and a["temporal_context"]["superseded_candidate_ids"]==[1]

def test_measurement_conversion_and_incompatible_methods_never_pool():
 a=c(1,None,candidate_type="MEASUREMENT",predicate="length",numeric_value=10,unit="mm",measurement_context={"sample_size":3},method_context={"class":"caliper"});b=c(2,None,candidate_type="MEASUREMENT",predicate="length",numeric_value=1,unit="cm",measurement_context={"sample_size":4},method_context={"class":"caliper"});r,_,_=execute([a,b]);m=r.versions[0]["measurement_summary"]
 assert m["compatible"] and m["observed_min"]==m["observed_max"]==10 and m["independent_sample_size_total"]==7 and m["pooled_estimate"] is None
 d=c(3,None,candidate_type="MEASUREMENT",predicate="length",numeric_value=9,unit="mm",method_context={"class":"image"});r,_,_=execute([a,d]);m=r.versions[0]["measurement_summary"];assert not m["compatible"] and m["pooled_estimate_prohibited"]

def test_consensus_is_multidimensional_and_never_truth_probability():
 r,_,_=execute([c(1),c(2),c(3)]);a=r.versions[0];assert a["aggregate_status"]==ConsensusStatus.STRONGLY_SUPPORTED and not a["confidence_dimensions"]["score_is_truth_probability"]
 r,_,_=execute([c(1)]);assert r.versions[0]["aggregate_status"]==ConsensusStatus.SINGLE_SOURCE

def test_idempotency_membership_rules_model_and_candidate_version_retain_history():
 r,s=setup();p=s.preview([c(1),c(2)]);s.execute(p["aggregate_run_id"]);p=s.preview([c(1),c(2)]);s.execute(p["aggregate_run_id"]);assert len(r.versions)==1
 p=s.preview([c(1),c(2),c(3)]);s.execute(p["aggregate_run_id"]);assert len(r.versions)==2 and sum(x["active"] for x in r.versions)==1
 changed=CandidateInput(**{**c(3).__dict__,"candidate_version":2});s2=EvidenceAggregationService(r,ruleset="086b-rules-2",model="086b-local-2");p=s2.preview([c(1),c(2),changed]);s2.execute(p["aggregate_run_id"]);assert len(r.versions)==3

def test_lifecycle_cancel_resume_partial_failure_reviews_and_tombstones():
 r,s=setup();p=s.preview([c(1),c(2,normalized_subject="Other")]);s.cancel(p["aggregate_run_id"]);assert s.execute(p["aggregate_run_id"])["state"]=="CANCELLED";assert s.resume(p["aggregate_run_id"])["state"]=="COMPLETED"
 before=list(r.members);review=next(iter(r.reviews));r.resolve_review(review,"DEFER","Requires expert review","owner");t=s.supersede(r.versions[0]["aggregate_id"],"retracted","owner");assert t in r.tombstones and r.members==before
 p=s.preview([c(3)]);r.items[p["aggregate_run_id"]][0]["candidates"]=[];assert s.execute(p["aggregate_run_id"])["state"]=="PARTIAL" and r.warnings

def test_copyright_safe_no_text_leak_and_no_publication_surface():
 r,_,_=execute([c(1,display_policy="METADATA_ONLY",metadata={"restricted_text":"secret"}),c(2,display_policy="INTERNAL_RESEARCH_ONLY",metadata={"restricted_text":"hidden"})]);a=r.versions[0]
 assert a["copyright_safe_display_state"]=="METADATA_ONLY" and "secret" not in str(a) and "hidden" not in str(a) and not a["published"]
 code="\n".join(x.read_text() for x in Path("app/evidence_aggregation").glob("*.py"));assert all(x not in code for x in ("production_publish","publish_node","publish_edge","final_scientific_answer","adapted_protocol","drive.files.update"))

def test_operator_api_has_plan_network_review_export_and_no_publication_endpoint():
 from app.evidence_aggregation.routes import router
 paths={x.path for x in router.routes};assert any("preview" in x for x in paths) and any("support-network" in x for x in paths) and any("contradiction-network" in x for x in paths) and any("export" in x for x in paths)
 assert not any("publish" in x for x in paths)
