# BUILD-618 implementation summary

Implemented a reusable causal applicability scope contract and integrated it through mechanistic candidate creation, contradiction analysis, and publication dry-run planning.

Key invariants:

- missing scope is `unknown`, never global;
- bounded scope requires at least one actual applicability bound;
- global scope requires an explicit justification and cannot carry local bounds;
- normalized scopes receive deterministic `scope_id` values;
- contradiction grouping uses normalized scope so different tissues/environments are not conflated;
- publication planning blocks unknown or invalid scope;
- projected graph payloads retain scope;
- no automatic review, contradiction resolution, publication authorization, or production graph write is added.

Validation remains infrastructure-blocked by GitHub issue #481 until hosted jobs execute workflow steps.
