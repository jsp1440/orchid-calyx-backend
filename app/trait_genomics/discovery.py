from __future__ import annotations

from collections import defaultdict
from hashlib import sha256

from .models import DiscoveryDataset, DiscoveryHypothesis, DiscoveryResult, EvidenceKind


TRAIT_KINDS = {
    EvidenceKind.OBSERVED_TRAIT,
    EvidenceKind.INFERRED_TRAIT,
    EvidenceKind.PREDICTED_TRAIT,
}
MOLECULAR_KINDS = {
    EvidenceKind.GENETIC_ASSOCIATION,
    EvidenceKind.EXPRESSION_ASSOCIATION,
}


class TraitGenomicsDiscoveryEngine:
    """Evidence-conservative cross-domain hypothesis generator.

    The engine detects repeated co-occurrence patterns linking a trait assertion,
    ecological interaction, and molecular feature within taxa. It never upgrades
    correlation to causation; causal_claim remains False until a separate reviewed
    mechanism workflow does so.
    """

    def discover(self, dataset: DiscoveryDataset) -> DiscoveryResult:
        by_taxon: dict[str, list] = defaultdict(list)
        for record in dataset.records:
            by_taxon[record.taxon_id].append(record)

        candidates: dict[tuple[str, str, str, str], dict] = {}
        for taxon_id, records in by_taxon.items():
            traits = [r for r in records if r.kind in TRAIT_KINDS]
            interactions = [r for r in records if r.kind == EvidenceKind.ECOLOGICAL_INTERACTION]
            molecular = [r for r in records if r.kind in MOLECULAR_KINDS]
            for trait in traits:
                trait_value = str(trait.value)
                for interaction in interactions or [None]:
                    interaction_key = ""
                    target = ""
                    if interaction is not None:
                        interaction_key = interaction.predicate
                        target = interaction.target_taxon_id or interaction.target_taxon_name or str(interaction.value or "")
                    for mol in molecular or [None]:
                        feature = ""
                        if mol is not None:
                            feature = mol.gene_id or mol.protein_id or mol.sequence_accession or mol.pathway_id or mol.predicate
                        key = (f"{trait.predicate}={trait_value}", interaction_key, target, feature)
                        item = candidates.setdefault(key, {"taxa": set(), "evidence": set(), "confidence": []})
                        item["taxa"].add(taxon_id)
                        item["evidence"].add(trait.evidence_id)
                        item["confidence"].append(trait.confidence)
                        if interaction is not None:
                            item["evidence"].add(interaction.evidence_id)
                            item["confidence"].append(interaction.confidence)
                        if mol is not None:
                            item["evidence"].add(mol.evidence_id)
                            item["confidence"].append(mol.confidence)

        hypotheses: list[DiscoveryHypothesis] = []
        for key, item in candidates.items():
            trait, interaction, target, feature = key
            # Repetition across at least two taxa is required for a discovery candidate.
            if len(item["taxa"]) < 2:
                continue
            mean_confidence = sum(item["confidence"]) / max(1, len(item["confidence"]))
            repetition_bonus = min(1.0, len(item["taxa"]) / 5.0)
            score = round(min(1.0, 0.75 * mean_confidence + 0.25 * repetition_bonus), 4)
            raw_id = "|".join(key) + "|" + "|".join(sorted(item["taxa"]))
            hypothesis_id = "OC-TIG-" + sha256(raw_id.encode("utf-8")).hexdigest()[:12].upper()
            hypotheses.append(
                DiscoveryHypothesis(
                    hypothesis_id=hypothesis_id,
                    taxon_scope=sorted(item["taxa"]),
                    trait_predicate=trait,
                    interaction_predicate=interaction or None,
                    interaction_target=target or None,
                    molecular_feature=feature or None,
                    support_count=len(item["evidence"]),
                    independent_taxa_count=len(item["taxa"]),
                    confidence=score,
                    evidence_ids=sorted(item["evidence"]),
                    rationale=(
                        "Repeated evidence pattern across taxa; candidate association only. "
                        "Requires phylogenetic correction, replication, and mechanistic review before causal interpretation."
                    ),
                )
            )

        hypotheses.sort(key=lambda h: (h.confidence, h.independent_taxa_count, h.support_count), reverse=True)
        records = dataset.records
        return DiscoveryResult(
            dataset_id=dataset.dataset_id,
            hypotheses=hypotheses,
            evidence_count=len(records),
            trait_count=sum(r.kind in TRAIT_KINDS for r in records),
            interaction_count=sum(r.kind == EvidenceKind.ECOLOGICAL_INTERACTION for r in records),
            molecular_count=sum(r.kind in MOLECULAR_KINDS for r in records),
        )
