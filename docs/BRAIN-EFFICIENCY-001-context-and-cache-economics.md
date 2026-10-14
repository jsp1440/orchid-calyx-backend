# BRAIN-EFFICIENCY-001: context reuse and prompt-cache economics

Status: draft implementation record. Mission classification: **NEW** for provider prompt caching (no existing branch or PR implements it). It **CONTINUEs** the existing routing, receipt and context-packet systems rather than replacing them.

Paired Brain change: `jsp1440/Orchid-Continuum-Brain`, branch `claude/orchid-brain-efficiency-qgbdm7` (context-packet fingerprint fix and the architecture record for KV-cache research).

## 1. Audit: what already existed

| Capability | State before this change | Where |
|---|---|---|
| Provider prompt caching | **Missing.** No request in either repository sent `cache_control` or `prompt_cache_key`. | — |
| Cache / token metrics | **Partial, unused.** `scripts/oc_cost_telemetry.py` parses `cache_*_input_tokens` but nothing in production calls it, and the direct executor dropped every usage field except input/output tokens. | `scripts/swarm_anthropic_direct.py`, `scripts/oc_cost_telemetry.py` |
| Model routing | **Implemented.** Deterministic cheap/standard/deep tier router, with repair and complexity promotion, env-overridable models and conservative cost reservations. | `scripts/oc_model_router.py`, `app/provider_reservoir/routing.py` |
| Budgets and kill switches | **Implemented.** NO-API guard (fails closed), governor kill switch, provider-error stop, per-run/daily/monthly budgets. These budget on *estimated* reservations, never actual cost. | `scripts/oc_no_api_guard.py`, `runtime/swarm/governor.py` |
| Persistent task context / resume | **Implemented.** Token-fenced program-worker leases, durable reservoir, work-packet fingerprints, `OC-SWARM-RESUME` exact-head resume, execution receipts. | `app/calyx_orchestrator/program_worker.py`, `durable_reservoir.py`, `runtime/swarm/work_packet.py` |
| Structured agent handoff | **Implemented.** Checker assignment/evidence records bound to exact heads; the Brain `oc.agent-context-packet.v1` cross-repo packet with a material fingerprint; dispatch receipts carry `context_fingerprint`. | `app/calyx_orchestrator/checker_dispatch.py`, Brain `scripts/oc_agent_context_packet.py` |
| Context-packet reuse | **Defective.** It is meant to publish only on material change, but replaying all 527 published packets showed a new fingerprint on **every** publish (see the Brain PR). | Brain |
| Engineering memory | Implemented, but not injected into any provider prompt. File fingerprints are used only to invalidate lessons. | `app/engineering_memory/` |

The paid coding lane (`orchid-completion-lane.yml`) has not run since 2026-09-11, and none of its logs record cache usage. **There is therefore no live production token baseline.** The before/after figures below are modelled, and are labelled that way everywhere they appear.

## 2. What changed (backend)

### 2.1 Direct Anthropic executor (`scripts/swarm_anthropic_direct.py`)

This is the provider path with the most repeated input: up to 24 turns, each one re-sending the tools, the instructions and the whole history.

- The fixed instructions now travel as `system`, with an explicit cache breakpoint. Render order is tools → system → messages, so this one breakpoint covers both tools and instructions. The per-task work packet is now the first user turn; it was previously concatenated after the instructions inside that turn. The instruction text itself is unchanged.
- A top-level `cache_control` lets the provider place a second breakpoint on the end of the growing history. That makes 2 breakpoints in total, against the provider maximum of 4.
- Usage now accumulates `cache_creation_input_tokens` and `cache_read_input_tokens` alongside input and output. These are written as `cacheCreationInputTokens` / `cacheReadInputTokens` in `modelUsage`, as `cache_*` keys in GitHub outputs, and in the `[OC-DIRECT-RECEIPT]` log line. A new `promptCache` field records whether caching was on. All additions are additive: the lane's `jq` only counts `modelUsage` entries.
- **Operator switch:** `OC_ANTHROPIC_PROMPT_CACHE=off` (also accepts `0`, `false`, `no`, `disabled`) sends no cache markers. No workflow, secret or variable was changed. The default is on, because caching changes billing, not what the model is given.

### 2.2 Engineering patch provider (`app/calyx_engineering/anthropic_provider.py`)

The bounded repair loop makes up to 3 attempts, and each one re-sends the same objective, constraints and repository files. The user turn is now split into two blocks:

1. A stable block (objective, constraints, files, response shape), sorted and marked for caching.
2. A per-attempt block (attempt number, failure logs).

The model receives the same information either way. The same operator switch applies.

### 2.3 Measurement tool (`scripts/oc_prompt_cache_benchmark.py`)

The tool is offline and spends nothing. It replays the request bodies the executor actually builds, turn by turn, through a model of the documented prefix-cache rules, and reports billed input with caching off and on:

- exact-byte prefix keys;
- breakpoint placement;
- the 20-position lookback;
- per-model minimum cacheable prefix;
- writes at 1.25×, reads at the read rate.

## 3. Before/after measurements

### 3.1 Prompt caching (modelled)

Command: `python scripts/oc_prompt_cache_benchmark.py --turns 24` (the router's cheap-tier turn budget). Tokens are estimated at about 4 characters per token, over a fixed synthetic read/search/write/check loop with 6 KB file reads.

| Tier (router default model) | Billed input, cache off | Billed input, cache on | Reduction | Cache hit rate | Est. input $/mission |
|---|---:|---:|---:|---:|---|
| cheap (`claude-haiku-4-5`, 4096-token minimum) | 233,171 | 50,117 | 78.5% | 89.4% | $0.2332 → $0.0501 |
| standard (`claude-sonnet-5`, 1024 minimum) | 233,171 | 45,443 | 80.5% | 91.7% | $0.4663 → $0.0909 |
| deep (`claude-opus-5`, 512 minimum) | 233,171 | 44,640 | 80.9% | 92.0% | $1.1659 → $0.2232 |

Short missions save less, because the first write is not yet repaid. At 6 turns the reduction is 34.9% (cheap), 59.2% (standard) and 63.4% (deep).

The cheap tier gains least because `claude-haiku-4-5` will not cache a prefix under 4096 tokens. The tools and instructions alone are below that, so only the growing history caches.

Output tokens are not affected. Caching does not change the amount of context the model processes (`processed_input_tokens` is identical on and off, and this is asserted in tests).

**Not measured:** live provider billing, real hit rates, TTL expiry between turns longer than 5 minutes, and handoff latency. The receipt fields added in §2.1 are how the first live run will measure all of these.

### 3.2 Context-packet reuse (measured, Brain)

`scripts/oc_agent_context_churn_replay.py` is read-only and works from git history only. It replayed the 527 packets published to `oc-agent-context-state` between 2026-10-03 and 2026-10-11:

- **Before:** 527 of 527 publishes carried a new fingerprint. A projection that only ignored `updated_at` and run IDs still skipped **0** of them. The real churn was `recent_runs`, a sliding window across every workflow on every branch.
- **After** (stable projection: heads, PRs, labels, bodies, classifications, and red workflows on governed branches): **116** material changes, with **411 of 527 (78.0%)** publishes skipped as non-material. The mean packet size is 164,732 bytes, so a stable fingerprint also lets a consumer skip re-reading an unchanged packet.

## 4. Safety properties (tested)

`tests/test_oc_prompt_cache.py` (21 tests) and `tests/test_calyx_anthropic_provider.py` (3 new tests) cover the following:

- **No stale scientific evidence.** The cache key is the exact prefix bytes. A single changed byte in an earlier tool result (a re-read file) means everything from that point is re-processed. The reads are asserted to stop before the changed block. A changed repository file likewise changes the repair provider's cached block.
- **No cross-task contamination.** The cached static prefix (tools and instructions) is asserted byte-identical across tasks and turns. Task B is asserted never to read more than that shared static prefix after task A has run.
- **No change to model input.** Instructions, packet, tools and history are unchanged in content. History is asserted append-only between turns, which caching requires.
- **Operator switch.** Turning caching off removes every marker and restores the uncached request.
- **Regression guard.** A mutation that put per-turn content into the system block made 3 tests fail; restoring the source returned them to green. The run used `python -B -p no:cacheprovider`.

Unchanged: scheduler and worker operation, queue leasing and claim fencing, idempotency, retry and recovery, provenance, budgets, NO-API mode and the kill switch. No new scheduler, queue or execution path was added.

## 5. Model routing evaluation

Routing already exists and is sound in shape: deterministic, no model call to choose a model, cheap by default, promoted by complexity, repair and priority signals, refused for provider-free work. No routing change was made. The defaults are an existing provider configuration and are left to the owner.

Observations for the owner:

- The cheap tier's default model, `claude-haiku-4-5`, has a 4096-token caching minimum. Current-generation models cache from 512 tokens, so the fixed prefix would cache from turn 1, at a lower list price than Haiku 4.5. `OC_CLAUDE_CHEAP_MODEL` is the existing override.
- Caches are scoped to a single model. Promoting a mission to a higher tier mid-lineage forfeits the cache, so promotion should stay a between-attempt decision. That is how the router already uses it.
- Governor reservations ($0.50 / $1.25 / $2.00) are not tightened. They should be revisited only after live receipts report real usage.

## 6. API prompt caching vs. internal KV-cache transfer

These are different mechanisms. Only the first is implemented.

- **API prompt caching** (this change): the provider stores its own attention state for a byte-identical request prefix inside one workspace, for one model, with a 5-minute (or 1-hour) TTL, and bills re-reads at a discount. It cannot transfer meaning between models. It cannot leak across tasks unless the bytes are identical. It requires no model runtime.
- **Cache-to-Cache (C2C) / cross-model KV transfer** (Fu et al., arXiv:2510.03215, ICLR 2026; covered by AlphaSignal): a trained projector fuses one open-weight model's KV-cache into another's, replacing text handoff between models. The reported results are about +8.5–10.5% accuracy over individual models, +3–5% over text communication, and roughly 2× lower latency. These figures were measured on small Qwen-family pairs.

Evaluation for Orchid Continuum: **not applicable today; worth revisiting only for a future self-hosted open-weight lane.** It requires direct access to model internals (hosted Claude/OpenAI APIs expose none), a trained fuser per model pair, and co-located GPU inference. It also replaces an auditable text or JSON handoff with an opaque tensor, which conflicts with the provenance rule that every handoff be inspectable. No implementation was attempted, consistent with the mission's authorization boundary. The detailed record lives in the Brain PR.

## 7. Limitations and follow-up

1. **Live verification.** The first authorized live run of the completion lane should be checked for `cacheReadInputTokens > 0` from turn 2 onward (turn 1 for current-generation models). If reads stay at zero, a silent invalidator exists.
2. **Actual-cost accounting.** The governor and GitHub ledger still budget on reservations; `total_cost_usd` and `actual_usd` remain unknown. Next step: price `modelUsage` (including cache fields) post-run in `swarm_governor_postrun.py`.
3. **Other provider paths.** The vision provider puts the static vocabulary after the image. Speak (OpenAI Responses) already orders its prefix stably but sends no `prompt_cache_key` and captures no usage. The hosted acceptance checker's prefix is below every caching minimum and is not worth changing.
4. **Durable reservoir fencing.** The audit found a holder string rather than a lease token, an unguarded `advance()`, and a check-then-act gap between `settle` and `complete`. This is outside this mission's scope but should be its own fix.
5. **Brain packet consumers.** Dispatch does not check packet age, and the packet covers 3 of the 7 allowlisted repositories (see the Brain PR).
