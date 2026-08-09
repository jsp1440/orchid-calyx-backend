# BUILD-618 validation note

Repository GitHub Actions remains affected by issue #481: hosted jobs fail before step 1 with `steps=null`. BUILD-618 therefore remains stacked/draft and must not merge until executable CI is restored.

Static review identified and fixed a scope re-normalization defect before PR creation: persisted normalized scope objects include derived `scope_id`; `normalize_causal_scope` now removes that derived field before strict model validation and recomputes it deterministically.

No production write, publication, Candidate Knowledge promotion, or graph mutation is authorized by this note.
