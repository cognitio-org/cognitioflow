"""relevance.py — a tiny, dependency-free TF-IDF ranker.

CognitioFlow uses it to pick, for a broad-scope game (several weeks or the whole course), the course material
most relevant to what the course examines: the past-exam and working-group text is the query, every other file is
scored against it, and the budget then fills with the files that best match the exam language. Pure Python stdlib —
it runs the same on the Mac and on Cloud Run, sends nothing anywhere, and adds no dependency.

This is deliberately lexical (TF-IDF cosine), not semantic: it is the honest first cut. A later phase can swap in the
shared RAG's embeddings for the score without changing callers — `rank` is the only seam.
"""
from __future__ import annotations
import math
import re
from collections import Counter

_WORD = re.compile(r"[a-z0-9]{3,}")          # drop one- and two-letter tokens; lowercase words and numbers (article refs)


def _tokens(text: str) -> list:
    return _WORD.findall((text or "").lower())


def _idf(docs_tokens: list) -> dict:
    """Inverse document frequency over the corpus being ranked, smoothed so a term in every doc still counts a little."""
    n, df = len(docs_tokens), Counter()
    for toks in docs_tokens:
        for t in set(toks):
            df[t] += 1
    return {t: math.log((1 + n) / (1 + c)) + 1 for t, c in df.items()}


def _vec(tokens: list, idf: dict) -> dict:
    tf = Counter(tokens)
    return {t: (c / len(tokens)) * idf.get(t, 0.0) for t, c in tf.items()} if tokens else {}


def _cosine(a: dict, b: dict) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(t, 0.0) for t, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def rank(query: str, docs: list) -> list:
    """Score each doc (a string) against the query by TF-IDF cosine. Returns a list of floats in docs' order,
    in [0, 1]. An empty query or empty docs scores 0.0, so callers fall back to their own order."""
    docs = [d or "" for d in docs]
    if not query.strip() or not any(d.strip() for d in docs):
        return [0.0] * len(docs)
    doc_tokens = [_tokens(d) for d in docs]
    idf = _idf(doc_tokens + [_tokens(query)])
    qv = _vec(_tokens(query), idf)
    return [_cosine(qv, _vec(dt, idf)) for dt in doc_tokens]
