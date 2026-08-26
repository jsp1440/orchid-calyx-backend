"""Lexical (BM25-equivalent) retrieval for engineering memory.

v1 ships portable lexical retrieval that runs identically on the SQLite dev/test
fallback and on PostgreSQL.  Candidate lessons are filtered by scope and status
in the database; ranking is computed in-process with a deterministic Okapi BM25
scorer over each lesson's ``lexical_document``.  This is a faithful
BM25-equivalent to a Postgres full-text ranking and keeps v1 free of a hard
pgvector dependency.

Semantic scoring is exposed as an optional adapter (:class:`EmbeddingAdapter`).
When — and only when — the deployed stack safely supports embeddings, an adapter
can be supplied and its cosine score is blended in.  Absent an adapter, lexical
retrieval is complete on its own.

Ranking policy (issue #1184):

* invalidated and expired lessons are excluded *before* scoring;
* verified lessons rank above otherwise-comparable candidates;
* at most five lessons are returned by default;
* an injected character budget caps how much text is emitted.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Protocol

from .models import LESSON_VERIFIED

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")

# BM25 free parameters (standard defaults).
_BM25_K1 = 1.5
_BM25_B = 0.75

# A verified lesson always outranks a comparable candidate.  We add a fixed
# dominance offset to verified scores rather than multiplying, so a verified
# lesson with any lexical overlap beats every candidate.
_VERIFIED_DOMINANCE = 1_000_000.0

DEFAULT_LIMIT = 5
DEFAULT_CHAR_BUDGET = 4000


def tokenize(text: str) -> list[str]:
    return [tok.lower() for tok in _TOKEN_RE.findall(text or "")]


class EmbeddingAdapter(Protocol):
    """Optional semantic-scoring adapter.

    Implementations return a cosine-like similarity in ``[0, 1]`` between a
    query and a lesson's stored embedding.  The core service never requires one.
    """

    def score(self, query: str, embedding: list | None) -> float: ...


@dataclass
class ScoredLesson:
    lesson: object  # EngineeringMemoryLesson
    score: float
    lexical_score: float
    semantic_score: float | None
    verified: bool
    rank: int = 0


@dataclass
class _Corpus:
    docs: list[list[str]] = field(default_factory=list)
    doc_freq: Counter = field(default_factory=Counter)
    avg_len: float = 0.0

    @classmethod
    def build(cls, documents: list[str]) -> "_Corpus":
        docs = [tokenize(d) for d in documents]
        df: Counter = Counter()
        for tokens in docs:
            for term in set(tokens):
                df[term] += 1
        avg_len = (sum(len(d) for d in docs) / len(docs)) if docs else 0.0
        return cls(docs=docs, doc_freq=df, avg_len=avg_len)

    def bm25(self, query_terms: list[str], doc_index: int) -> float:
        tokens = self.docs[doc_index]
        if not tokens:
            return 0.0
        counts = Counter(tokens)
        n = len(self.docs)
        length = len(tokens)
        score = 0.0
        for term in query_terms:
            tf = counts.get(term, 0)
            if not tf:
                continue
            df = self.doc_freq.get(term, 0)
            # idf with +1 smoothing keeps scores non-negative.
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            denom = tf + _BM25_K1 * (
                1 - _BM25_B + _BM25_B * (length / self.avg_len if self.avg_len else 1)
            )
            score += idf * (tf * (_BM25_K1 + 1)) / denom
        return score


def rank_lessons(
    query: str,
    lessons: list,
    *,
    limit: int = DEFAULT_LIMIT,
    char_budget: int = DEFAULT_CHAR_BUDGET,
    embedding_adapter: EmbeddingAdapter | None = None,
    semantic_weight: float = 0.5,
) -> tuple[list[ScoredLesson], int]:
    """Rank ``lessons`` for ``query`` and apply limit + character budget.

    Returns ``(scored, injected_chars)``.  ``lessons`` must already be filtered
    to a single scope and to returnable statuses by the caller.
    """

    query_terms = tokenize(query)
    corpus = _Corpus.build([getattr(les, "lexical_document", "") or "" for les in lessons])

    scored: list[ScoredLesson] = []
    for idx, lesson in enumerate(lessons):
        lexical = corpus.bm25(query_terms, idx)
        semantic: float | None = None
        combined = lexical
        if embedding_adapter is not None:
            semantic = float(
                embedding_adapter.score(query, getattr(lesson, "embedding", None))
            )
            combined = (1 - semantic_weight) * lexical + semantic_weight * semantic
        verified = getattr(lesson, "status", None) == LESSON_VERIFIED
        rank_score = combined + (_VERIFIED_DOMINANCE if verified else 0.0)
        scored.append(
            ScoredLesson(
                lesson=lesson,
                score=rank_score,
                lexical_score=lexical,
                semantic_score=semantic,
                verified=verified,
            )
        )

    # Deterministic ordering: score desc, then verified first, then newest,
    # then stable id tiebreak.
    def _created(les: object) -> float:
        created = getattr(les, "created_at", None)
        return created.timestamp() if created is not None else 0.0

    scored.sort(
        key=lambda s: (
            -s.score,
            0 if s.verified else 1,
            -_created(s.lesson),
            str(getattr(s.lesson, "lesson_id", "")),
        )
    )

    # Drop zero-signal results (no lexical or semantic overlap at all).  A
    # verified lesson with no term overlap is still not relevant to the query.
    scored = [s for s in scored if s.lexical_score > 0 or (s.semantic_score or 0) > 0]

    # Apply limit.
    scored = scored[: max(0, limit)]

    # Apply character budget: keep whole lessons until the budget is exhausted.
    injected_chars = 0
    budgeted: list[ScoredLesson] = []
    for s in scored:
        doc_len = len(getattr(s.lesson, "lexical_document", "") or "")
        if injected_chars + doc_len > char_budget and budgeted:
            break
        budgeted.append(s)
        injected_chars += doc_len

    for rank, s in enumerate(budgeted, start=1):
        s.rank = rank

    return budgeted, injected_chars
