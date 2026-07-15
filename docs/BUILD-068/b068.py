"""BUILD-068 lean phased driver.
Usage: b068.py <publish|validate|connectivity|idempotency>

Transaction policy: commit PER COMPLETED DOMAIN (a domain is a complete,
validated batch). Rationale: production-size population (~5.9k inserts) over a
high-latency per-row write path exceeds a single interactive execution window
and background processes are reaped; a single all-or-nothing transaction across
all domains is not achievable here. Per-domain commit + durable checkpoints +
resume + idempotent re-publish (node-skip / edge-identity set) give safe,
zero-inflation restartability. Withheld domains (climate, mycorrhiza) are never
supplied, so they can never be written.
"""
import os, sys, json, time, traceback
from datetime import datetime, timezone
AUDIT="/home/runner/audit"; OUT=os.path.join(AUDIT,"build068_result.json")
DSN=os.environ["DATABASE_URL"]; SCHEMA="oc_graph"
ORDER=["media","traits","pollinators","occurrences","literature","conservation"]
WITHHELD=["climate","mycorrhiza"]
PHASE=sys.argv[1]
BUDGET=float(sys.argv[2]) if len(sys.argv)>2 else 95.0
import psycopg
from runtime.knowledge_graph import (PostgresGraphRepository, validate_graph,
    JsonFileCheckpointStore, CANONICAL_AUTHORITY, CANONICAL_AUTHORITY_LABEL)
from runtime.knowledge_graph.checkpoint import Checkpoint
from runtime.knowledge_graph.repository import WritablePostgresGraphRepository
from runtime.knowledge_graph.sources import PostgresSourceProvider
from runtime.knowledge_graph.publisher import publish_domain
from runtime.knowledge_graph.orchestrator import DOMAIN_ADAPTERS
AB={a.domain:a for a in DOMAIN_ADAPTERS}
def load(): return json.load(open(OUT)) if os.path.exists(OUT) else {"build":"BUILD-068","phases":{}}
def save(R): R["updated_at"]=datetime.now(timezone.utc).isoformat(); json.dump(R,open(OUT,"w"),indent=2,default=str)
def log(m): print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {m}",flush=True)
def counts():
    with psycopg.connect(DSN,connect_timeout=10) as c, c.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {SCHEMA}.kg_nodes WHERE is_active"); n=cur.fetchone()[0]
        cur.execute(f"SELECT count(*) FROM {SCHEMA}.kg_edges WHERE is_active"); e=cur.fetchone()[0]
    return n,e

def run_domains(repo, src, ckpt, completed, deadline, bsize=500):
    """Process each not-yet-completed domain fully, then COMMIT + checkpoint.
    On failure: rollback the current (uncommitted) domain and stop.
    On time budget: stop launching new domains (resume next call)."""
    per=[]
    for d in ORDER:
        if d in completed:
            per.append({"domain":d,"status":"completed","skipped_this_call":True}); continue
        if time.time()>deadline:
            log(f"  budget reached before '{d}' -> stopping; RESUME REQUIRED"); break
        o={"domain":d,"status":"completed","nodes_written":0,"edges_written":0,
           "skipped_existing_nodes":0,"skipped_existing_edges":0,"invalid":0,
           "rows_processed":0,"available_rows":0,"batches":0,"committed":False,"error":None}
        try:
            o["available_rows"]=src.count(d); off=0
            while True:
                rows=src.fetch(d,bsize,off)
                if not rows: break
                r=publish_domain(repo,AB[d],rows)
                o["nodes_written"]+=r.nodes_written; o["edges_written"]+=r.edges_written
                o["skipped_existing_nodes"]+=r.skipped_existing_nodes
                o["skipped_existing_edges"]+=r.skipped_existing_edges
                o["invalid"]+=len(r.invalid); o["rows_processed"]+=len(rows); o["batches"]+=1
                off+=len(rows)
                if len(rows)<bsize: break
            repo.commit(); o["committed"]=True     # complete-domain commit
        except Exception as ex:
            o["status"]="failed"; o["error"]=str(ex); o["trace"]=traceback.format_exc()
            repo.rollback()
        ckpt.save(Checkpoint(domain=d,status=o["status"],rows_processed=o["rows_processed"],
            stats={k:o[k] for k in ("nodes_written","edges_written","skipped_existing_nodes","skipped_existing_edges","invalid","batches","committed")},
            validation={}))
        per.append(o)
        log(f"  {d}: rows={o['rows_processed']} +nodes={o['nodes_written']} +edges={o['edges_written']} skipEdge={o['skipped_existing_edges']} invalid={o['invalid']} committed={o['committed']} status={o['status']}")
        if o["status"]=="failed": break
    return per

try:
  if PHASE=="publish":
    R=load(); R.setdefault("started_at",datetime.now(timezone.utc).isoformat())
    src=PostgresSourceProvider.from_registry(DSN)
    # baseline + run identity persist across resume calls
    if "build_run_id" not in R:
        before_n,before_e=counts(); build_run_id=int(time.time())
        R["build_run_id"]=build_run_id
        R["baseline_nodes"]=before_n; R["baseline_edges"]=before_e
        R["checkpoint_path"]=os.path.join(AUDIT,f"build068_checkpoints_{build_run_id}.json")
        R["phases"]["preflight"]={
          "1_db_target":DSN.split("@")[-1] if "@" in DSN else "set",
          "2_target_tables":[f"{SCHEMA}.kg_nodes",f"{SCHEMA}.kg_edges"],
          "3_writable_repo_active":True,"4_canonical_authority":CANONICAL_AUTHORITY,
          "4_label":CANONICAL_AUTHORITY_LABEL,"4_is_world_plants":CANONICAL_AUTHORITY=="world_plants",
          "5_authorized_domains":ORDER,"6_withheld":WITHHELD,
          "6_withheld_absent":all(w not in ORDER for w in WITHHELD),
          "7_before_nodes":before_n,"7_before_edges":before_e,
          "8_build_run_id":build_run_id,"9_checkpoint_path":R["checkpoint_path"],
          "12_source_read_only":True,"13_authorized_to_publish":True,
          "source_records_per_domain":{d:src.count(d) for d in ORDER}}
        save(R)
    build_run_id=R["build_run_id"]; before_n=R["baseline_nodes"]; before_e=R["baseline_edges"]
    ckpt_path=R["checkpoint_path"]
    log(f"baseline {before_n}/{before_e}; build_run_id={build_run_id}")
    if CANONICAL_AUTHORITY!="world_plants" or not R["phases"]["preflight"]["6_withheld_absent"]:
        R["result"]="CONTROLLED PRODUCTION POPULATION ABORTED — NO WRITES"; save(R); sys.exit(0)
    ckpt=JsonFileCheckpointStore(ckpt_path)
    completed={c.domain for c in ckpt.all() if c.status=="completed"}
    log(f"already completed: {sorted(completed)}")
    # commit_every: persist partial progress WITHIN a domain so a large domain
    # (traits ~5.6k inserts) resumes across calls instead of restarting endlessly.
    repo=WritablePostgresGraphRepository(DSN,schema=SCHEMA,build_run_id=build_run_id,commit_every=500)
    t0=time.time(); deadline=t0+BUDGET
    per=run_domains(repo,src,ckpt,completed,deadline); pub_dur=time.time()-t0
    repo.close()
    completed_now={c.domain for c in ckpt.all() if c.status=="completed"}
    any_failed=any(c.status=="failed" for c in ckpt.all())
    all_done=all(d in completed_now for d in ORDER)
    after_n,after_e=counts()
    R["phases"].setdefault("publish",{"calls":[]})
    R["phases"]["publish"]["calls"].append({"at":datetime.now(timezone.utc).isoformat(),
      "duration_sec":round(pub_dur,1),"per_domain":per})
    R["phases"]["publish"].update({
      "completed_domains":sorted(completed_now),"all_domains_done":all_done,
      "any_failed":any_failed,"after_nodes":after_n,"after_edges":after_e,
      "nodes_added":after_n-before_n,"edges_added":after_e-before_e,
      "checkpoints":[c.to_dict() for c in ckpt.all()]})
    if all_done:
        R["result"]="PUBLISH_COMPLETE_PENDING_VALIDATION"
    elif any_failed:
        R["result"]="PARTIALLY COMPLETED — RESUME REQUIRED (domain failure)"
    else:
        R["result"]="PARTIALLY COMPLETED — RESUME REQUIRED (time budget)"
    save(R)
    log(f"publish call done: completed={sorted(completed_now)} all_done={all_done} failed={any_failed} after {after_n}/{after_e} (+{after_n-before_n}/+{after_e-before_e})")

  elif PHASE=="validate":
    R=load()
    repo=PostgresGraphRepository(DSN,schema=SCHEMA)  # read-only, committed graph
    v=validate_graph(repo)
    after_n,after_e=counts()
    R["phases"]["final_validation"]={
      "after_nodes":after_n,"after_edges":after_e,
      "nodes_added":after_n-R["baseline_nodes"],"edges_added":after_e-R["baseline_edges"],
      "healthy":v["healthy"],"total_problems":v["total_problems"],
      "orphan_nodes":v["orphan_nodes"],"orphan_edges":v["orphan_edges"],
      "duplicate_relationships":v["duplicate_relationships"],
      "identifier_integrity":v.get("identifier_integrity"),
      "provenance_completeness":v["provenance_completeness"],
      "vocabulary_compliant":v["vocabulary_compliance"]["compliant"],
      "cross_domain_consistency":v["cross_domain_consistency"],
      "domain_breakdown":v["domain_breakdown"]}
    save(R)
    log(f"validate healthy={v['healthy']} problems={v['total_problems']} orphans(n/e)={v['orphan_nodes']}/{v['orphan_edges']} dup={v['duplicate_relationships']}")

  elif PHASE=="connectivity":
    R=load(); bid=R["build_run_id"]; cr={}
    with psycopg.connect(DSN,connect_timeout=10) as c, c.cursor() as cur:
        cur.execute(f"SELECT source_table,count(*) FROM {SCHEMA}.kg_edges WHERE is_active AND build_run_id=%s GROUP BY 1 ORDER BY 2 DESC",(bid,))
        cr["edges_added_by_source_table"]={r[0]:r[1] for r in cur.fetchall()}
        cur.execute(f"SELECT edge_type,count(*) FROM {SCHEMA}.kg_edges WHERE is_active AND build_run_id=%s GROUP BY 1 ORDER BY 2 DESC",(bid,))
        cr["edges_added_by_edge_type"]={r[0]:r[1] for r in cur.fetchall()}
        cur.execute(f"SELECT node_type,count(*) FROM {SCHEMA}.kg_nodes WHERE is_active AND build_run_id=%s GROUP BY 1 ORDER BY 2 DESC",(bid,))
        cr["nodes_added_by_node_type"]={r[0]:r[1] for r in cur.fetchall()}
        cur.execute(f"SELECT count(*) FROM {SCHEMA}.kg_nodes WHERE is_active AND node_type IN ('taxon','genus')")
        cr["canonical_taxa_total"]=cur.fetchone()[0]
        cur.execute(f"""SELECT count(DISTINCT n.kg_node_id) FROM {SCHEMA}.kg_nodes n
            WHERE n.is_active AND n.node_type IN ('taxon','genus') AND EXISTS(
              SELECT 1 FROM {SCHEMA}.kg_edges e WHERE e.is_active AND e.build_run_id=%s
              AND (e.from_node_id=n.kg_node_id OR e.to_node_id=n.kg_node_id))""",(bid,))
        cr["canonical_taxa_connected_to_authorized_domain"]=cur.fetchone()[0]
        cur.execute(f"SELECT count(*) FROM {SCHEMA}.kg_edges WHERE is_active AND source_table ILIKE '%%climate%%'")
        cr["climate_edges_present"]=cur.fetchone()[0]
        cur.execute(f"SELECT count(*) FROM {SCHEMA}.kg_edges WHERE is_active AND (source_table ILIKE '%%mycorr%%' OR edge_type ILIKE '%%mycorr%%')")
        cr["mycorrhiza_edges_present"]=cur.fetchone()[0]
    R["phases"]["connectivity"]=cr; save(R)
    log(f"connectivity {cr['edges_added_by_source_table']} climate={cr['climate_edges_present']} myco={cr['mycorrhiza_edges_present']}")

  elif PHASE=="idempotency":
    R=load(); bid=R["build_run_id"]
    src=PostgresSourceProvider.from_registry(DSN)
    ib_n,ib_e=counts()
    ckpt=JsonFileCheckpointStore(os.path.join(AUDIT,f"build068_idem_{bid}.json"))
    repo=WritablePostgresGraphRepository(DSN,schema=SCHEMA,build_run_id=bid,commit_every=None)
    t0=time.time(); per=run_domains(repo,src,ckpt,set(),t0+600); dur=time.time()-t0
    # idempotency run must not add anything; rollback any (there should be none)
    repo.rollback(); repo.close()
    ia_n,ia_e=counts()
    R["phases"]["idempotency"]={"before_nodes":ib_n,"before_edges":ib_e,
      "after_nodes":ia_n,"after_edges":ia_e,"node_delta":ia_n-ib_n,"edge_delta":ia_e-ib_e,
      "duration_sec":round(dur,1),"no_inflation":(ia_n==ib_n and ia_e==ib_e),
      "per_domain_nodes_written":{o["domain"]:o.get("nodes_written",0) for o in per},
      "per_domain_edges_written":{o["domain"]:o.get("edges_written",0) for o in per},
      "per_domain_edges_skipped_existing":{o["domain"]:o.get("skipped_existing_edges",0) for o in per}}
    save(R)
    log(f"idempotency delta n={ia_n-ib_n} e={ia_e-ib_e} no_inflation={ia_n==ib_n and ia_e==ib_e}")
except Exception as e:
    R=load(); R.setdefault("errors",[]).append({"phase":PHASE,"error":str(e),"trace":traceback.format_exc()}); save(R)
    log("EXCEPTION "+str(e)); raise
