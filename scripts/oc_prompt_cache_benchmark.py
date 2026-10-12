"""Deterministic prompt-cache accounting for the direct Anthropic executor.

This replays the request bodies that ``scripts/swarm_anthropic_direct.py``
actually builds, turn by turn, through a model of the provider's documented
prefix-cache rules, and reports billed input with caching off and on. It makes
no network call and spends nothing.

What it is: a measurement of how the executor's *request shape* interacts with
prefix caching. What it is not: a measurement of provider billing. Token counts
are estimated from bytes (``CHARS_PER_TOKEN``), and the transcript is a fixed
synthetic tool loop. Real hit rates come from ``cacheReadInputTokens`` in the
executor's ``[OC-DIRECT-RECEIPT]`` once the lane runs live.

Cache rules modelled (Anthropic prompt caching, as documented):
  * render order is tools -> system -> messages; a cache entry is keyed by the
    exact bytes of the prefix up to a ``cache_control`` breakpoint;
  * a top-level ``cache_control`` places one breakpoint on the last block;
  * a breakpoint can read the longest earlier entry whose prefix it extends,
    looking back at most 20 block positions;
  * a prefix shorter than the model's minimum is neither written nor read;
  * writes bill at 1.25x base input (5-minute TTL), reads at the model's read
    rate, everything after the last breakpoint at 1x.

    python scripts/oc_prompt_cache_benchmark.py            # all router tiers
    python scripts/oc_prompt_cache_benchmark.py --turns 24 --json
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "swarm_anthropic_direct", REPO_ROOT / "scripts" / "swarm_anthropic_direct.py"
)
assert _SPEC and _SPEC.loader
direct = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(direct)

CHARS_PER_TOKEN = 4
LOOKBACK_POSITIONS = 20
WRITE_MULTIPLIER = 1.25


@dataclass(frozen=True)
class ModelCacheTerms:
    """Published per-model terms. Prices are USD per million input tokens."""

    model: str
    input_usd_per_mtok: float
    read_multiplier: float
    minimum_cacheable_tokens: int


# The router's default tier models (scripts/oc_model_router.py DEFAULT_MODELS),
# with list prices and cache minimums as published at the time of writing. They
# are inputs to an estimate, not billing truth; pass --terms to override.
DEFAULT_TERMS = {
    "cheap": ModelCacheTerms("claude-haiku-4-5", 1.00, 0.10, 4096),
    "standard": ModelCacheTerms("claude-sonnet-5", 2.00, 0.10, 1024),
    "deep": ModelCacheTerms("claude-opus-5", 5.00, 0.10, 512),
}


def _tokens(value: Any) -> int:
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    return max(1, -(-len(text.encode("utf-8")) // CHARS_PER_TOKEN))


def _strip_marker(block: Any) -> Any:
    if isinstance(block, dict):
        return {k: v for k, v in block.items() if k != "cache_control"}
    return block


def render_positions(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten a request into ordered cacheable positions.

    Each position carries the cumulative digest of every byte before and
    including it (``cache_control`` markers excluded, since a moving marker is
    not part of the cached content), its token estimate, and whether an explicit
    breakpoint sits on it.
    """
    blocks: list[tuple[Any, bool]] = []
    for tool in body.get("tools") or []:
        blocks.append((_strip_marker(tool), "cache_control" in tool))
    system = body.get("system")
    if isinstance(system, str):
        blocks.append(({"type": "text", "text": system}, False))
    elif isinstance(system, list):
        for block in system:
            blocks.append((_strip_marker(block), "cache_control" in block))
    for message in body.get("messages") or []:
        content = message["content"]
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        for index, block in enumerate(content):
            marked = isinstance(block, dict) and "cache_control" in block
            # The role is part of the rendered bytes of a message's first block.
            blocks.append(
                (
                    {"role": message["role"], "i": index, "b": _strip_marker(block)},
                    marked,
                )
            )

    positions = []
    digest = hashlib.sha256()
    cumulative = 0
    for block, marked in blocks:
        encoded = json.dumps(block, sort_keys=True, separators=(",", ":"))
        digest.update(encoded.encode("utf-8"))
        cumulative += _tokens(encoded)
        positions.append(
            {
                "key": digest.copy().hexdigest(),
                "tokens": cumulative,
                "breakpoint": marked,
            }
        )
    if positions and "cache_control" in body:
        positions[-1]["breakpoint"] = True  # top-level automatic breakpoint
    return positions


@dataclass
class ProviderCacheModel:
    """In-memory model of one workspace's prefix cache (TTL assumed unexpired)."""

    minimum_tokens: int
    entries: dict[str, int] = field(default_factory=dict)

    def bill(self, body: dict[str, Any]) -> dict[str, int]:
        positions = render_positions(body)
        total = positions[-1]["tokens"] if positions else 0
        breakpoints = [i for i, p in enumerate(positions) if p["breakpoint"]]
        read = 0
        for bp in breakpoints:
            for i in range(bp, max(-1, bp - LOOKBACK_POSITIONS - 1), -1):
                cached = self.entries.get(positions[i]["key"])
                if cached is not None:
                    read = max(read, cached)
                    break
        written_to = read
        for bp in breakpoints:
            tokens = positions[bp]["tokens"]
            if tokens >= self.minimum_tokens:
                self.entries.setdefault(positions[bp]["key"], tokens)
                written_to = max(written_to, tokens)
        write = written_to - read
        return {
            "input_tokens": total - written_to,
            "cache_creation_input_tokens": write,
            "cache_read_input_tokens": read,
        }


def synthetic_tool_loop(
    turns: int, packet: str, file_bytes: int = 6000
) -> list[list[dict[str, Any]]]:
    """Message histories for a deterministic read/search/write/check loop.

    Turn shapes mirror the executor: one assistant turn with a tool_use run,
    then one user turn with the matching tool_result run. File bodies are
    deterministic so the replay is reproducible.
    """
    histories = []
    messages: list[dict[str, Any]] = [{"role": "user", "content": packet}]
    tools = ("read_file", "search_text", "read_file", "write_file", "run_check")
    for turn in range(1, turns + 1):
        histories.append([dict(m) for m in messages])
        name = tools[(turn - 1) % len(tools)]
        tool_id = f"toolu_{turn:04d}"
        messages.append(
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": f"Step {turn}: using {name}."},
                    {
                        "type": "tool_use",
                        "id": tool_id,
                        "name": name,
                        "input": {"path": f"app/module_{turn % 7}.py"},
                    },
                ],
            }
        )
        body = (f"# module {turn % 7} line\n" * (file_bytes // 24))[:file_bytes]
        result = body if name in {"read_file", "search_text"} else "OK"
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": tool_id, "content": result}
                ],
            }
        )
    return histories


def replay(
    terms: ModelCacheTerms, *, turns: int, packet: str, cache: bool
) -> dict[str, Any]:
    model = ProviderCacheModel(terms.minimum_cacheable_tokens)
    totals = {
        "input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    for history in synthetic_tool_loop(turns, packet):
        body = direct._request_body(
            model=terms.model, messages=history, max_tokens=3072, cache=cache
        )
        for key, value in model.bill(body).items():
            totals[key] += value
    processed = sum(totals.values())
    billed_equivalent = (
        totals["input_tokens"]
        + WRITE_MULTIPLIER * totals["cache_creation_input_tokens"]
        + terms.read_multiplier * totals["cache_read_input_tokens"]
    )
    return {
        **totals,
        "processed_input_tokens": processed,
        "billed_input_token_equivalent": round(billed_equivalent),
        "estimated_input_usd": round(
            billed_equivalent * terms.input_usd_per_mtok / 1_000_000, 4
        ),
        "cache_hit_rate": round(totals["cache_read_input_tokens"] / processed, 4)
        if processed
        else 0.0,
    }


def benchmark(
    turns: int = 24, terms: dict[str, ModelCacheTerms] | None = None
) -> dict[str, Any]:
    packet = (
        "OC-SWARM work packet\n" + "Acceptance criterion and bounded context.\n" * 40
    )
    rows = {}
    for tier, model_terms in (terms or DEFAULT_TERMS).items():
        before = replay(model_terms, turns=turns, packet=packet, cache=False)
        after = replay(model_terms, turns=turns, packet=packet, cache=True)
        saved = (
            before["billed_input_token_equivalent"]
            - after["billed_input_token_equivalent"]
        )
        rows[tier] = {
            "terms": asdict(model_terms),
            "before": before,
            "after": after,
            "billed_input_reduction": round(
                saved / before["billed_input_token_equivalent"], 4
            ),
        }
    return {
        "basis": "modelled: executor request bodies replayed through documented prefix-cache rules",
        "chars_per_token": CHARS_PER_TOKEN,
        "turns": turns,
        "tiers": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--turns", type=int, default=24)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = benchmark(args.turns)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    print(f"{result['basis']} ({args.turns} turns, ~{CHARS_PER_TOKEN} chars/token)")
    for tier, row in result["tiers"].items():
        b, a = row["before"], row["after"]
        print(
            f"{tier:9s} {row['terms']['model']:18s} billed-input {b['billed_input_token_equivalent']:>9,} -> "
            f"{a['billed_input_token_equivalent']:>9,} ({row['billed_input_reduction']:.1%} less); "
            f"hit rate {a['cache_hit_rate']:.1%}; est ${b['estimated_input_usd']:.4f} -> ${a['estimated_input_usd']:.4f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
