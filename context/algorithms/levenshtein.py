"""
levenshtein.py — Wagner-Fischer Levenshtein edit distance and similarity.

Why this instead of difflib.SequenceMatcher:
  SequenceMatcher uses LCS (longest common subsequence) ratio, which measures
  shared substrings. Levenshtein measures the minimum number of single-character
  edits (insertions, deletions, substitutions) to transform one string into another.

  For short identity strings (company names, person names, email addresses),
  Levenshtein is more precise because:
  - "GE Healthcare" vs "GE Helthcare" → edit distance = 1 (1 sub), ratio ≈ 0.93
  - SequenceMatcher gives ~0.88 for the same pair (LCS treats runs differently)
  - At the dedup threshold boundary (0.65–0.82), this precision matters

  For long free-text fields (communication notes, deal descriptions), prefer
  SequenceMatcher or semantic similarity (MCP scorer).

Public API:
  edit_distance(a, b)           → int   (Wagner-Fischer O(m*n))
  similarity(a, b)              → float (1 - distance/max_len, 0.0..1.0)
  levenshtein_ratio(a, b)       → float (alias for similarity, same contract
                                         as SequenceMatcher.ratio())

  SimilarityScorer               Protocol for injectable scorers
  LevenshteinScorer              Default implementation (no external deps)
  MCPScorer                      Stub — inject a real MCP caller at runtime
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


def edit_distance(a: str, b: str) -> int:
    """Wagner-Fischer dynamic programming Levenshtein distance.

    Time:  O(m * n)
    Space: O(min(m, n))  (two-row rolling array)
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    # Keep shorter string in inner loop for space efficiency
    if len(a) < len(b):
        a, b = b, a

    m, n = len(a), len(b)
    prev = list(range(n + 1))
    curr = [0] * (n + 1)

    for i in range(1, m + 1):
        curr[0] = i
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                curr[j] = prev[j - 1]
            else:
                curr[j] = 1 + min(
                    prev[j],      # deletion
                    curr[j - 1],  # insertion
                    prev[j - 1],  # substitution
                )
        prev, curr = curr, prev

    return prev[n]


def similarity(a: str, b: str) -> float:
    """Levenshtein-based similarity in [0.0, 1.0].

    similarity = 1 - (edit_distance / max(len(a), len(b)))
    Returns 1.0 for identical strings, 0.0 when one is empty.
    """
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    max_len = max(len(a), len(b))
    return 1.0 - (edit_distance(a, b) / max_len)


# Alias matching SequenceMatcher.ratio() contract for drop-in replacement
levenshtein_ratio = similarity


@runtime_checkable
class SimilarityScorer(Protocol):
    """Injectable similarity scorer protocol.

    Implement this to swap Levenshtein for semantic or MCP-based scoring.
    The contract is: score(left, right) → float in [0.0, 1.0].
    """

    def score(self, left: str, right: str, **kwargs: Any) -> float:
        """Return similarity score between two strings."""
        ...


class LevenshteinScorer:
    """Default scorer using Wagner-Fischer edit distance.

    Suitable for:
    - Company names, contact names (short identity strings)
    - Email addresses, domain names

    Not ideal for:
    - Long free-text notes (use SequenceMatcher or MCPScorer)
    - Semantic equivalence ("GE" vs "General Electric")
    """

    def score(self, left: str, right: str, **kwargs: Any) -> float:
        return similarity(left, right)


class MCPScorer:
    """Placeholder for MCP/semantic similarity scoring.

    Use this when:
    - Communication note content comparison (semantic, not lexical)
    - Company name fuzzy matching where abbreviations are common
      ("GE" vs "General Electric Healthcare")
    - Any case where edit distance alone produces too many false negatives

    To activate: inject a real `call_fn` at construction time.
    call_fn(left, right) must return float in [0.0, 1.0].

    If call_fn is None, falls back to LevenshteinScorer.
    This ensures the pipeline never hard-fails due to an unavailable MCP server.
    """

    def __init__(self, call_fn=None):
        self._call_fn = call_fn
        self._fallback = LevenshteinScorer()

    def score(self, left: str, right: str, **kwargs: Any) -> float:
        if self._call_fn is not None:
            try:
                result = self._call_fn(left, right, **kwargs)
                return float(result)
            except Exception:
                pass  # MCP unavailable → fall back silently
        return self._fallback.score(left, right)


# Module-level default — used by dedupe.py unless overridden
_DEFAULT_SCORER: SimilarityScorer = LevenshteinScorer()


def get_scorer() -> SimilarityScorer:
    """Return the current module-level scorer."""
    return _DEFAULT_SCORER


def set_scorer(scorer: SimilarityScorer) -> None:
    """Replace the module-level scorer (e.g., inject MCPScorer at startup)."""
    global _DEFAULT_SCORER
    _DEFAULT_SCORER = scorer


from context.algorithms._instrumentation import log_debug  # noqa: E402

edit_distance = log_debug(
    edit_distance,
    stat_fn=lambda result, a, b, **_: {"call_count": 1},
    sample_fn=lambda result, a, b, **_: {"a": a[:50], "b": b[:50], "distance": result},
    max_samples=50,
)
similarity = log_debug(
    similarity,
    stat_fn=lambda result, a, b, **_: {"call_count": 1},
    sample_fn=lambda result, a, b, **_: {"a": a[:50], "b": b[:50], "similarity": round(result, 4)},
    max_samples=50,
)
levenshtein_ratio = similarity  # re-point alias to the wrapped version
