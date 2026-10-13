"""Verified links from World Plants names to Knowledge Graph taxon nodes.

``CanonicalRegistry`` (BUILD-065) identifies taxa by an ordinal ``canonical_id``
assigned in row order, and ``oc_graph.kg_nodes`` identifies species as
``taxon:<public.taxonomy_species.id>``.  Neither carries the other's identifier,
so every bridge between them is a name join -- and a name join is exactly where
one species is silently substituted for another.

This module builds the bridge and refuses every case it cannot prove unique:

* a registry homonym (one canonical name, several World Plants rows);
* a *pro parte* synonym (one synonym name, several accepted taxa);
* a synonym name that is also an accepted name;
* a name that ``canonical_name_of`` would collapse (``var.``/``subsp.``/``f.``,
  hybrid markers, or author particles such as ``van den``);
* several active graph taxon nodes carrying the same canonical label;
* a graph node labelled with a *synonym* (the graph treats it as a separate
  taxon; mapping either way would substitute one for the other);
* an external authority identifier that disagrees between both sides.

Each link uses the taxon-link vocabulary of the Functional Interaction Layer
contract (#1810): ``status`` in ``accepted | synonym | ambiguous | unresolved``,
``authority = world_plants``, ``automatic_fuzzy_matching = False``.  Only
``accepted`` and ``synonym`` links yield a node key.

Pure and read-only: callers pass rows they have already read; nothing here
opens a connection or writes to the graph.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .canonical_taxonomy import (
    CANONICAL_AUTHORITY,
    MAP_ACCEPTED_NAME,
    MAP_EXACT_ID,
    MAP_MANUAL_REVIEW,
    SYNONYM,
    CanonicalRegistry,
    canonical_name_of,
    rank_of,
)

MAPPING_VERSION = "oc-taxon-graph-mapping-v1"
MATCH_METHOD = "exact_canonical_name"

ACCEPTED = "accepted"
LINK_SYNONYM = "synonym"
AMBIGUOUS = "ambiguous"
UNRESOLVED = "unresolved"
LINKED_STATUSES = frozenset({ACCEPTED, LINK_SYNONYM})

REGISTRY_HOMONYM = "REGISTRY_HOMONYM"
PRO_PARTE_SYNONYM = "PRO_PARTE_SYNONYM"
SYNONYM_IS_ACCEPTED_NAME = "SYNONYM_IS_ACCEPTED_NAME"
SYNONYM_TARGET_NOT_LINKED = "SYNONYM_TARGET_NOT_LINKED"
NAME_NORMALIZATION_UNSAFE = "NAME_NORMALIZATION_UNSAFE"
GRAPH_NODE_NOT_FOUND = "GRAPH_NODE_NOT_FOUND"
GRAPH_DUPLICATE_LABEL = "GRAPH_DUPLICATE_LABEL"
GRAPH_HAS_SEPARATE_NODE_FOR_SYNONYM = "GRAPH_HAS_SEPARATE_NODE_FOR_SYNONYM"
AUTHORITY_ID_CONFLICT = "AUTHORITY_ID_CONFLICT"

_RANK_MARKERS = frozenset({"subsp.", "ssp.", "var.", "subvar.", "f.", "fo.", "forma", "nothosubsp.", "nothovar."})
_HYBRID_MARKERS = frozenset({"x", "×"})
_EPITHET = re.compile(r"^[a-z][a-z-]*$")
_GENUS = re.compile(r"^[A-Z][a-z]+$")


def strict_name_key(scientific_name: str | None) -> str:
    """Genus, epithet and any infraspecific rank and epithet, nothing else.

    Unlike ``canonical_name_of`` this keeps rank markers and stops at the
    first token that is not part of the name, so author particles never
    become epithets.  Used only to detect names the shared normaliser would
    collapse; it is not a second identity scheme.
    """

    tokens = str(scientific_name or "").replace("&amp;", "&").split()
    out: list[str] = []
    i = 0
    if i < len(tokens) and tokens[i] in _HYBRID_MARKERS:
        out.append("×")
        i += 1
    if i >= len(tokens) or not _GENUS.match(tokens[i]):
        return " ".join(tokens)
    out.append(tokens[i])
    i += 1
    if i < len(tokens) and tokens[i] in _HYBRID_MARKERS:
        out.append("×")
        i += 1
    if i < len(tokens) and _EPITHET.match(tokens[i]):
        out.append(tokens[i])
        i += 1
        if i + 1 < len(tokens) and tokens[i] in _RANK_MARKERS and _EPITHET.match(tokens[i + 1]):
            out.extend((tokens[i], tokens[i + 1]))
    return " ".join(out)


def normalization_safe(scientific_name: str | None) -> bool:
    return canonical_name_of(scientific_name) == strict_name_key(scientific_name)


def _key(name: str | None) -> str:
    return canonical_name_of(name).casefold()


@dataclass(frozen=True)
class TaxonGraphLink:
    canonical_name: str
    registry_status: str
    status: str
    node_key: str | None
    accepted_name: str | None
    rank: str | None
    reasons: tuple[str, ...] = ()
    mapping_class: str = MAP_MANUAL_REVIEW
    candidate_node_keys: tuple[str, ...] = ()
    method: str = MATCH_METHOD
    authority: str = CANONICAL_AUTHORITY
    automatic_fuzzy_matching: bool = False
    release: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_name": self.canonical_name,
            "registry_status": self.registry_status,
            "status": self.status,
            "node_key": self.node_key,
            "accepted_name": self.accepted_name,
            "rank": self.rank,
            "reasons": list(self.reasons),
            "mapping_class": self.mapping_class,
            "candidate_node_keys": list(self.candidate_node_keys),
            "method": self.method,
            "authority": self.authority,
            "automatic_fuzzy_matching": self.automatic_fuzzy_matching,
            "release": self.release,
        }


@dataclass(frozen=True)
class TaxonGraphMapping:
    links: dict[str, TaxonGraphLink]
    release: dict[str, Any] | None = None
    version: str = MAPPING_VERSION
    graph_issues: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def link_for_name(self, name: str | None) -> TaxonGraphLink | None:
        return self.links.get(_key(name))

    def node_key_for_name(self, name: str | None) -> str | None:
        link = self.link_for_name(name)
        return link.node_key if link is not None and link.status in LINKED_STATUSES else None

    def taxon_node_key(self, registry: CanonicalRegistry) -> Callable[[int], str | None]:
        """Adapter for ``GraphGroundedReasoner``: registry id -> verified key or None."""

        def key(canonical_id: int) -> str | None:
            taxon = registry.taxa.get(canonical_id)
            return self.node_key_for_name(taxon.canonical_name) if taxon else None

        return key

    def summary(self) -> dict[str, Any]:
        by_status: dict[str, int] = defaultdict(int)
        by_reason: dict[str, int] = defaultdict(int)
        for link in self.links.values():
            by_status[link.status] += 1
            for reason in link.reasons:
                by_reason[reason] += 1
        return {
            "version": self.version,
            "release": self.release,
            "names": len(self.links),
            "by_status": dict(sorted(by_status.items())),
            "by_reason": dict(sorted(by_reason.items())),
            "graph_duplicate_labels": sum(
                1 for v in self.graph_issues.values() if GRAPH_DUPLICATE_LABEL in v
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary(),
            "links": [self.links[k].to_dict() for k in sorted(self.links)],
        }


def _node_field(node: Any, name: str, default: Any = None) -> Any:
    if isinstance(node, Mapping):
        return node.get(name, default)
    return getattr(node, name, default)


def _graph_index(graph_nodes: Iterable[Any]) -> tuple[dict[str, list[str]], dict[str, dict[str, set[str]]]]:
    by_label: dict[str, list[str]] = defaultdict(list)
    ids: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for node in graph_nodes:
        if _node_field(node, "node_type") != "taxon":
            continue
        if _node_field(node, "is_active", True) is False:
            continue
        key = str(_node_field(node, "canonical_key") or "")
        label = _node_field(node, "display_label")
        if not key or not label:
            continue
        by_label[_key(label)].append(key)
        payload = _node_field(node, "payload") or {}
        for authority, value in (payload.get("authority_ids") or {}).items():
            ids[key][str(authority).upper()].add(str(value))
    return {k: sorted(set(v)) for k, v in by_label.items()}, ids


def build_taxon_graph_mapping(
    load_rows: Iterable[Mapping[str, Any]],
    synonym_rows: Iterable[Mapping[str, Any]] = (),
    graph_nodes: Iterable[Any] = (),
    authority_rows: Iterable[Mapping[str, Any]] = (),
    release: dict[str, Any] | None = None,
) -> TaxonGraphMapping:
    """Link every World Plants name to at most one graph taxon node.

    ``load_rows`` and ``synonym_rows`` have the shapes ``build_canonical_registry``
    consumes.  ``graph_nodes`` are ``runtime.knowledge_graph.models.Node`` or
    dicts with ``canonical_key``, ``node_type``, ``display_label`` and optional
    ``is_active`` and ``payload.authority_ids``.  ``authority_rows`` carry
    ``canonical_name``, ``authority`` and ``external_id``.
    """

    accepted_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in load_rows:
        name = str(row.get("name") or "").replace("&amp;", "&").strip()
        if not canonical_name_of(name):
            continue
        accepted_rows[_key(name)].append({"name": name, "rank": rank_of(row.get("taxon_code"))})

    synonym_targets: dict[str, set[str]] = defaultdict(set)
    synonym_names: dict[str, str] = {}
    for row in synonym_rows:
        if str(row.get("relationship") or "").lower() != SYNONYM:
            continue
        raw = row.get("input_match_name") or row.get("input_name")
        syn = _key(raw)
        acc = _key(row.get("accepted_match_name") or row.get("accepted_name"))
        if syn and acc and syn != acc:
            synonym_targets[syn].add(acc)
            synonym_names.setdefault(syn, str(raw))

    registry_ids: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for row in authority_rows:
        name = _key(row.get("canonical_name") or row.get("name"))
        if name and row.get("external_id") not in (None, ""):
            registry_ids[name][str(row.get("authority") or "").upper()].add(str(row["external_id"]))

    by_label, node_ids = _graph_index(graph_nodes)
    graph_issues = {label: (GRAPH_DUPLICATE_LABEL,) for label, keys in by_label.items() if len(keys) > 1}
    links: dict[str, TaxonGraphLink] = {}

    for key, rows in accepted_rows.items():
        name = canonical_name_of(rows[0]["name"])
        reasons: list[str] = []
        if len({(r["name"], r["rank"]) for r in rows}) > 1:
            reasons.append(REGISTRY_HOMONYM)
        if any(not normalization_safe(r["name"]) for r in rows):
            reasons.append(NAME_NORMALIZATION_UNSAFE)
        if key in synonym_targets:
            reasons.append(SYNONYM_IS_ACCEPTED_NAME)
        candidates = tuple(by_label.get(key, ()))
        if not candidates:
            reasons.append(GRAPH_NODE_NOT_FOUND)
        elif len(candidates) > 1:
            reasons.append(GRAPH_DUPLICATE_LABEL)
        mapping_class = MAP_ACCEPTED_NAME
        if not reasons:
            mine = registry_ids.get(key, {})
            theirs = node_ids.get(candidates[0], {})
            shared = set(mine) & set(theirs)
            if any(mine[a] != theirs[a] for a in shared):
                reasons.append(AUTHORITY_ID_CONFLICT)
            elif shared:
                mapping_class = MAP_EXACT_ID
        if reasons:
            status = UNRESOLVED if reasons == [GRAPH_NODE_NOT_FOUND] else AMBIGUOUS
            links[key] = TaxonGraphLink(
                canonical_name=name,
                registry_status=ACCEPTED,
                status=status,
                node_key=None,
                accepted_name=name,
                rank=rows[0]["rank"] if len(rows) == 1 else None,
                reasons=tuple(reasons),
                mapping_class=MAP_MANUAL_REVIEW,
                candidate_node_keys=candidates,
                release=release,
            )
        else:
            links[key] = TaxonGraphLink(
                canonical_name=name,
                registry_status=ACCEPTED,
                status=ACCEPTED,
                node_key=candidates[0],
                accepted_name=name,
                rank=rows[0]["rank"],
                mapping_class=mapping_class,
                candidate_node_keys=candidates,
                release=release,
            )

    for key, targets in synonym_targets.items():
        if key in accepted_rows:
            continue  # recorded on the accepted link as SYNONYM_IS_ACCEPTED_NAME
        name = canonical_name_of(synonym_names[key])
        reasons = []
        if len(targets) > 1:
            reasons.append(PRO_PARTE_SYNONYM)
        if not normalization_safe(synonym_names[key]):
            reasons.append(NAME_NORMALIZATION_UNSAFE)
        own_nodes = tuple(by_label.get(key, ()))
        if own_nodes:
            reasons.append(GRAPH_HAS_SEPARATE_NODE_FOR_SYNONYM)
        target = links.get(next(iter(targets))) if len(targets) == 1 else None
        if not reasons and (target is None or target.status != ACCEPTED):
            reasons.append(SYNONYM_TARGET_NOT_LINKED)
        if reasons:
            links[key] = TaxonGraphLink(
                canonical_name=name,
                registry_status=LINK_SYNONYM,
                status=AMBIGUOUS if reasons != [SYNONYM_TARGET_NOT_LINKED] else UNRESOLVED,
                node_key=None,
                accepted_name=target.accepted_name if target else None,
                rank=None,
                reasons=tuple(reasons),
                candidate_node_keys=own_nodes,
                release=release,
            )
        else:
            links[key] = TaxonGraphLink(
                canonical_name=name,
                registry_status=LINK_SYNONYM,
                status=LINK_SYNONYM,
                node_key=target.node_key,
                accepted_name=target.accepted_name,
                rank=target.rank,
                mapping_class=target.mapping_class,
                candidate_node_keys=(target.node_key,),
                release=release,
            )

    return TaxonGraphMapping(links=links, release=release, graph_issues=graph_issues)
