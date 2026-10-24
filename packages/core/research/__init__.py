"""Retrieval, claim verification and originality checking for factual scripts.

Everything here is deterministic and offline-testable: the network is reached
through an injected fetcher, and nothing a page returns is ever treated as an
instruction. Page text is untrusted bytes, so it is bounded in size, stripped
of markup and control characters, and kept as evidence rather than executed.
"""
from __future__ import annotations

from .history import ProductionHistory, production_history
from .originality import OriginalityReport, check_originality, prior_scripts_from, similarity, trigrams
from .retrieval import FetchedSource, fetch_sources, http_fetch, retrieve_or_raise
from .verification import (
    Claim,
    ClaimCheck,
    VerificationReport,
    build_report,
    check_claims,
    normalize,
    verification_status,
)

__all__ = [
    "Claim",
    "ClaimCheck",
    "FetchedSource",
    "OriginalityReport",
    "ProductionHistory",
    "VerificationReport",
    "build_report",
    "check_claims",
    "check_originality",
    "fetch_sources",
    "http_fetch",
    "normalize",
    "prior_scripts_from",
    "production_history",
    "retrieve_or_raise",
    "similarity",
    "trigrams",
    "verification_status",
]
