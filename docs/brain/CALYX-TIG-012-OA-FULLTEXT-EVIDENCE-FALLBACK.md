# CALYX TIG-012 — Open-Access Full-Text Evidence Fallback

## Purpose

TIG-012 extends the Europe PMC molecular evidence harvester beyond abstracts without relaxing the scientific acceptance boundary. When an adaptively retrieved publication has gene/protein annotations but no qualifying abstract sentence, Calyx may inspect Europe PMC Open Access `fullTextXML` content for the same strict sentence-level association pattern.

## Scientific boundary

A molecular candidate still requires one sentence containing:

- a Europe PMC gene/protein annotation;
- a controlled orchid trait term; and
- an explicit association, expression, selection, regulation, QTL, or locus relation term.

For open-access full-text fallback, the containing paragraph must additionally include the configured target taxon's scientific name. This prevents evidence about another species in a multi-taxon paper from being assigned automatically to the target orchid.

All harvested candidates remain review-only. No candidate becomes live TIG molecular evidence until human acceptance through the governed review layer.

## Source policy

Full text is requested only from Europe PMC's documented Open Access `/{pmcid}/fullTextXML` endpoint. Unavailable, restricted, malformed, or transient full-text responses fail closed and do not become evidence. The harvester does not bulk-download restricted papers.

## Diagnostics

The harvest result now reports:

- `full_text_attempted`
- `full_text_available`
- `full_text_candidates`

Candidate provenance records whether evidence came from `abstract` or `open_access_full_text` and includes the full-text section label when available.

## Additional correctness fix

The sentence scanner now evaluates every sentence containing the annotated gene/protein rather than only the first mention. A later sentence may qualify if—and only if—it independently satisfies the full same-sentence trait and relation gate.
