"""
Text tokenization for retrieval
================================

Shared tokenization used by the keyword scorer and the IDF index. Pure stdlib.

Pipeline: lowercase -> split on non-alphanumeric -> drop stopwords -> Porter
stem. This is what gives lexical retrieval its real recall:

- punctuation-robust: ``queries.`` and ``queries`` and ``rate-limit`` all
  tokenize the same way (the old ``str.split()`` did not);
- morphology-robust: ``authenticate``/``authentication`` collapse to one stem;
- stopword-aware: ``how do i fix the auth bug`` no longer dilutes the score
  with ``how/do/i/the`` — only ``fix/auth/bug`` count.

It does NOT handle synonyms or abbreviations (``auth`` != ``authentication``);
that is the job of the optional semantic lane, not lexical matching.
"""

import math
import re
from typing import Dict, Iterable, List

from rainman.core.porter import stem

# Common English + developer filler words that carry ~no retrieval signal.
STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "if", "then", "else", "of", "to",
    "in", "on", "at", "by", "for", "with", "from", "into", "is", "are", "was",
    "were", "be", "been", "being", "do", "does", "did", "done", "have", "has",
    "had", "i", "you", "he", "she", "it", "we", "they", "this", "that", "these",
    "those", "as", "so", "not", "no", "yes", "can", "will", "would", "should",
    "could", "how", "what", "when", "where", "why", "which", "who", "whom",
    "my", "our", "your", "their", "its", "his", "her", "me", "us", "them",
    "about", "up", "out", "down", "over", "under", "again", "just", "than",
    "too", "very", "s", "t", "use", "using", "used", "get", "got",
})

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str, *, keep_stopwords: bool = False) -> List[str]:
    """Lowercase, split on non-alphanumeric, drop stopwords, Porter-stem.

    Tokens of length 1 are dropped (except pure digits) as noise. Returns a
    list (with duplicates preserved) so callers can compute term frequencies.
    """
    if not text:
        return []
    out: List[str] = []
    for raw in _TOKEN_RE.findall(text.lower()):
        if len(raw) < 2 and not raw.isdigit():
            continue
        if not keep_stopwords and raw in STOPWORDS:
            continue
        out.append(stem(raw))
    return out


def tokenize_query(query_words: Iterable[str]) -> List[str]:
    """Tokenize a query given as raw words/phrases.

    Each element may itself contain punctuation (e.g. ``"rate-limit"``), so we
    tokenize every element and flatten. De-duplication is left to the caller.
    """
    out: List[str] = []
    for w in query_words:
        out.extend(tokenize(w))
    return out


def tokenize_refs(file_refs: Iterable[str]) -> List[str]:
    """Tokenize file paths into searchable stems (plus the bare filename stem).

    ``services/api/auth.py`` -> stems of {services, api, auth, py} + {auth}.
    """
    out: List[str] = []
    for ref in file_refs:
        normalized = ref.replace("\\", "/")
        out.extend(tokenize(normalized.replace("/", " ").replace(".", " ")))
        basename = normalized.split("/")[-1]
        out.extend(tokenize(basename))
    return out


def build_idf(corpus_token_sets: List[set]) -> Dict[str, float]:
    """Inverse document frequency over a corpus of per-document token *sets*.

    idf(t) = ln(1 + N / df(t)) — smoothed so a term present in every document
    still has a small positive weight, and rare terms dominate ranking. This is
    BM25's term-weighting principle; combined with stemmed tokenization it is
    what lets ``saturation`` outrank ``the``/``bug`` in a query.
    """
    n = len(corpus_token_sets)
    if n == 0:
        return {}
    df: Dict[str, int] = {}
    for tokens in corpus_token_sets:
        for t in tokens:
            df[t] = df.get(t, 0) + 1
    return {t: math.log(1 + n / count) for t, count in df.items()}
