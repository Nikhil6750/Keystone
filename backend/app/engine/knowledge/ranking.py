"""Deterministic lexical relevance scoring -- no embeddings, no model
calls, no arbitrary model-generated relevance judgment.

**Tokenization**: case-normalized (lowercased), alphanumeric runs only
(`[a-z0-9]+`), via a fixed regular expression -- the same input string
always tokenizes to the same token list, independent of locale, platform,
or any external state.

**Stopwords**: an explicit, fixed, documented set of common English
function words (`DEFAULT_STOPWORDS`) removed from the *query* side only
before scoring -- never from indexed content, so a document's own term
frequencies are never altered by this choice. Passing `stopwords=frozenset()`
disables the strategy entirely; there is no implicit, undocumented
filtering anywhere else in this module.

**Scoring formula**, evidence-weighted and bounded to `[0.0, 1.0]`: for
each *distinct* query term (after stopword removal), a term score
combines three explicit, weighted signals --

- content term frequency (capped/saturating, so one term repeated 50
  times cannot dominate the score),
- whether the term appears in the document's title,
- whether the term appears in the chunk's heading path,

plus a single, document-wide exact-phrase bonus if the full (stripped,
case-folded) query string appears verbatim as a substring of the chunk's
content. The per-term scores are averaged over *all* query terms (not just
the matched ones, so a chunk matching only some of a multi-term query
scores lower than one matching all of it), then the whole thing is
normalized by the maximum theoretically achievable weight sum -- giving a
score that is always in `[0.0, 1.0]`, with `0.0` reserved for "no query
terms matched at all." No current time or randomness enters this
computation anywhere.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass

from app.engine.knowledge.errors import MalformedKnowledgeDataError
from app.engine.knowledge.models import KnowledgeChunk

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# A small, fixed, explicit English stopword list -- not an ML model, not
# locale-aware, just the handful of function words common enough to add
# noise to naive term-overlap scoring. Documented here in full; nothing
# else in this module filters tokens implicitly.
DEFAULT_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "with",
    }
)

# Diminishing-returns cap on how many occurrences of one query term in a
# chunk's content still count toward its term-frequency component --
# beyond this, additional repeats add nothing further.
_TERM_FREQUENCY_SATURATION = 3


def tokenize(text: str) -> list[str]:
    """Deterministic, case-normalized tokenization: lowercase, then every
    maximal run of ASCII letters/digits is one token."""
    return _TOKEN_RE.findall(text.lower())


@dataclass(frozen=True)
class RankingWeights:
    """Explicit, documented weights for lexical scoring. No subjective
    "model prestige" or brand-preference term exists anywhere in this
    type -- every weight corresponds to a directly observable match
    signal."""

    content_term_frequency_weight: float = 1.0
    title_match_weight: float = 2.0
    heading_match_weight: float = 1.5
    exact_phrase_bonus: float = 1.0

    def __post_init__(self) -> None:
        weights = (
            self.content_term_frequency_weight,
            self.title_match_weight,
            self.heading_match_weight,
            self.exact_phrase_bonus,
        )
        if any(not math.isfinite(w) for w in weights):
            raise MalformedKnowledgeDataError("ranking weights must be finite numbers")
        if min(weights) < 0:
            raise MalformedKnowledgeDataError("ranking weights must not be negative")
        if sum(weights) <= 0:
            raise MalformedKnowledgeDataError("ranking weights must not all be zero")

    @property
    def max_weight_sum(self) -> float:
        return (
            self.content_term_frequency_weight
            + self.title_match_weight
            + self.heading_match_weight
            + self.exact_phrase_bonus
        )


def extract_query_terms(query: str, *, stopwords: frozenset[str] = DEFAULT_STOPWORDS) -> set[str]:
    """The distinct, stopword-filtered token set for `query`. Empty for a
    blank query or a query consisting entirely of stopwords -- callers
    treat an empty result as "no query terms to search for," never as an
    error."""
    return {token for token in tokenize(query) if token not in stopwords}


def score_chunk(
    chunk: KnowledgeChunk,
    *,
    title: str,
    query: str,
    query_terms: set[str],
    weights: RankingWeights,
) -> tuple[float, tuple[str, ...]]:
    """The bounded `[0.0, 1.0]` relevance score of `chunk` against
    `query_terms` (already stopword-filtered, from `extract_query_terms`),
    plus the sorted tuple of query terms that actually matched (in
    content, title, or heading). `(0.0, ())` when `query_terms` is empty
    or nothing matched -- never a division by zero, since `query_terms`'s
    length only appears as a denominator after this module confirms it is
    non-empty."""
    if not query_terms:
        return 0.0, ()

    content_counts = Counter(tokenize(chunk.content))
    title_terms = set(tokenize(title))
    heading_terms = set(tokenize(" ".join(chunk.heading_path)))

    matched_terms: list[str] = []
    term_scores: list[float] = []
    for term in sorted(query_terms):
        term_frequency = content_counts.get(term, 0)
        in_title = term in title_terms
        in_heading = term in heading_terms
        if term_frequency == 0 and not in_title and not in_heading:
            continue
        matched_terms.append(term)
        saturation = min(term_frequency, _TERM_FREQUENCY_SATURATION) / _TERM_FREQUENCY_SATURATION
        term_scores.append(
            weights.content_term_frequency_weight * saturation
            + (weights.title_match_weight if in_title else 0.0)
            + (weights.heading_match_weight if in_heading else 0.0)
        )

    if not term_scores:
        return 0.0, ()

    average_term_score = sum(term_scores) / len(query_terms)
    phrase = query.strip().lower()
    phrase_bonus = weights.exact_phrase_bonus if phrase and phrase in chunk.content.lower() else 0.0

    bounded = (average_term_score + phrase_bonus) / weights.max_weight_sum
    bounded = max(0.0, min(1.0, bounded))
    return bounded, tuple(matched_terms)


__all__ = [
    "DEFAULT_STOPWORDS",
    "RankingWeights",
    "extract_query_terms",
    "score_chunk",
    "tokenize",
]
