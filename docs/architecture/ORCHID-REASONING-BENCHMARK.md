# Orchid Scientific Reasoning Benchmark: Real Questions, Independent Review

**Contract:** `oc-orchid-reasoning-real-v1`
**Code:** `app/graph_grounded_reasoning/real_benchmark.py`
**Data:** `benchmarks/orchid_reasoning_real/{suite,sources,cases,reviews}.json`
**Validate:** `PYTHONPATH=. python scripts/validate_orchid_reasoning_benchmark.py`
**Stacked on:** #1831, which builds on #1829 and #1819.

## Status

**There are no cases yet.** The committed suite is valid and empty (`status: AWAITING_CASES`), and `score_suite` returns `REFUSED_NO_SCORABLE_CASES`. No accuracy figure exists, and none may be reported, until cases go through the review protocol below.

The synthetic benchmark under `benchmarks/graph_grounded_reasoning/` stays a *contract* benchmark. Its labels come from how the fixture was built, so it cannot show scientific accuracy.

## What a case is

A case is one real question, the source documents that bear on it, and two or more independent expert reviews. The case itself carries no expected answer. Any expected answer is derived from the reviews.

| Record | Required content |
|---|---|
| **Case** (`cases.json`) | `case_id`, `version`, `category` (one of the eight below), `facet` (pilot `Facet`), `question` as asked, `question_origin {type, model_generated: false, recorded_at}`, `split` (`dev`/`heldout`), `source_document_ids` |
| **Source** (`sources.json`) | `document_id`; `rights_state` (#1182 vocabulary); `citation` (Brain KO-0030: `title`, `author_or_creator`, `publication_year`, and `url_or_identifier` or `citation_text`); `locator` (page/section); optional `excerpt` + `excerpt_sha256` |
| **Review** (`reviews.json`) | `case_id`; `reviewer_id` (pseudonymous); `qualification`; `reviewed_at`; `independent: true`; `model_assisted: false`; `review_status` (Brain KO-0024); `answer_state` (SCIAN-002 `InferenceState`); `supporting_document_ids`; `contradicting_document_ids` |

**Categories** (the mission's eight): `taxonomy_synonymy`, `morphological_identification`, `species_description`, `pollination_biology`, `mycorrhizal_associations`, `geographic_distribution`, `conflicting_literature`, `uncertain_incomplete`.

**Question origins:** `member_submitted`, `expert_authored`, `literature_derived`, `operational_log`. A model-generated question is refused. #1775 records that the reference paper's temporal test used LLM-generated questions; this protocol does not.

## How a label is derived

- **Scorable.** At least **two** reviews have `independent: true`, `review_status` of `expert_reviewed` or `source_verified`, distinct reviewers, and the **same** `answer_state`. That shared state is the expected state.
- **Expected documents** are those every such reviewer cited as supporting. **Acceptable documents** are those any of them cited, supporting or contradicting. A citation outside the acceptable set counts as an unsupported citation.
- **Disagreement.** Reviewers disagree on the state. The case is recorded with every reviewer's state and is **not** scored as right or wrong. Instead it reports whether each system avoided a confident `CANDIDATE`.
- **Insufficient review.** Fewer than two qualifying reviews. The case is excluded from scoring.

## What the validator refuses

The validator refuses a suite outright; it never repairs one. It refuses:
- **Fixture labels:** a fixture-derived `label_source`.
- **The question:** a model-generated or undeclared question origin.
- **Where the answer comes from:**
  - a case that carries its own `expected_state` or `expected_documents`;
  - a review that is model-assisted, or does not declare it.
- **What reviewers cite:**
  - a review citing a document the case does not list;
  - a non-abstaining review with no supporting document.
- **Duplicates and orphans:** duplicate reviewers, and reviews for unknown cases.
- **Sources:** unknown rights states, and incomplete citations or locators.
- **Excerpts:**
  - stored excerpts on any source that is not `PUBLIC_DOMAIN` / `OPEN_LICENSE`;
  - excerpts longer than 300 characters, or with a hash mismatch.
- **Leakage:** a source document shared by `dev` and `heldout` cases.

## Scoring

`score_suite(suite, systems, split="heldout", external_model_systems=...)` scores every system on **the same** validated, scorable cases. The per-case and aggregate metrics are those of the #1819 harness (`score_case`, `aggregate`), using reviewer-derived expectations:
- state accuracy;
- answer/abstain accuracy;
- citation precision against the acceptable documents, and recall against the consensus documents;
- unsupported citations;
- abstention precision and recall;
- conflict retention;
- median latency;
- provider calls and cost.

A system named in `external_model_systems` receives only cases whose sources permit model transmission (`PUBLIC_DOMAIN`, `OPEN_LICENSE` or `INTERNAL_TDM_PERMITTED`). Cases it skipped are listed. This enforces #1182's rule that a document's availability does not by itself permit external-model processing.

## Compatibility

- `to_evaluation_case` emits the `app.evals.EvaluationCase` shape proposed in #1379–#1383 (`case_id`, `version`, `task_class_id`, `input_ref`, `expected_ref`, `provenance`). The set can move into `oc_evals.cases` when that stack lands.
- Sources are expected to come from, and be shared with, the #1182 botanical gold set, so the two do not become separate truths.

## Collecting cases

The owner or scientific reviewers decide this; nothing here is automated.
1. Collect real questions, for example from member submissions, Calyx operational logs (with privacy review) or expert authorship. Record their origin and date.
2. Register the source documents with rights evidence. Store an excerpt only where the rights state allows.
3. Assign each case to at least two independent qualified reviewers. Reviewers do not see each other's answers or any system output.
4. Commit the cases, sources and reviews, run the validator, and freeze the `heldout` split before any system is compared on it.
5. Score the literature-only baseline and the graph-grounded pilot on the same split. Report per-category values and the disagreement subset, and report no accuracy improvement unless it is measured here.
