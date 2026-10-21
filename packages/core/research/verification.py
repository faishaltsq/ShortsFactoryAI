"""Check that a script's factual claims are actually supported by its sources.

A claim is supported only when its quoted evidence appears in the retrieved text
of the source it cites. Absence of a quotation is recorded as unsupported;
absence of the source itself is recorded as unverified, because "we could not
read the page" is a different fact from "the page disagrees".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..schemas import VerificationStatus
from .retrieval import FetchedSource

MIN_QUOTE_CHARS = 12
_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")

SUPPORTED = "supported"
UNSUPPORTED = "unsupported"
UNVERIFIED = "unverified"


@dataclass(frozen=True)
class Claim:
    statement: str
    quote: str
    source_url: str


@dataclass(frozen=True)
class ClaimCheck:
    statement: str
    status: str
    source_url: str
    quote: str = ""
    matched: str = ""
    reason: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "statement": self.statement,
            "status": self.status,
            "source_url": self.source_url,
            "quote": self.quote,
            "matched": self.matched,
            "reason": self.reason,
        }


@dataclass
class VerificationReport:
    status: VerificationStatus
    checks: list[ClaimCheck] = field(default_factory=list)
    retrieved: int = 0

    @property
    def supported(self) -> list[ClaimCheck]:
        return [c for c in self.checks if c.status == SUPPORTED]

    @property
    def unsupported(self) -> list[ClaimCheck]:
        return [c for c in self.checks if c.status == UNSUPPORTED]

    @property
    def unverified(self) -> list[ClaimCheck]:
        return [c for c in self.checks if c.status == UNVERIFIED]


def normalize(text: str) -> str:
    """Casefold, drop punctuation, collapse whitespace: the form used for matching."""
    return _WHITESPACE.sub(" ", _PUNCTUATION.sub(" ", text.casefold())).strip()


def _index(sources: list[FetchedSource]) -> dict[str, FetchedSource]:
    return {source.url: source for source in sources}


def check_claims(claims: list[Claim], sources: list[FetchedSource]) -> list[ClaimCheck]:
    """Match every claim quote against the retrieved text of the source it cites."""
    by_url = _index(sources)
    checks: list[ClaimCheck] = []
    for claim in claims:
        statement = claim.statement.strip()
        quote = claim.quote.strip()
        url = claim.source_url.strip()
        source = by_url.get(url)
        if source is None:
            checks.append(ClaimCheck(statement, UNVERIFIED, url, quote, reason="source was not retrieved"))
            continue
        if source.status != "ok" or not source.text:
            checks.append(
                ClaimCheck(statement, UNVERIFIED, url, quote, reason=f"source status {source.status}")
            )
            continue
        normalized_quote = normalize(quote)
        if len(normalized_quote) < MIN_QUOTE_CHARS:
            checks.append(
                ClaimCheck(
                    statement, UNVERIFIED, url, quote,
                    reason=f"quote is shorter than {MIN_QUOTE_CHARS} normalized characters",
                )
            )
            continue
        if normalized_quote in normalize(source.text):
            checks.append(ClaimCheck(statement, SUPPORTED, url, quote, matched=quote, reason="quote found"))
        else:
            checks.append(
                ClaimCheck(statement, UNSUPPORTED, url, quote, reason="quote not found in retrieved text")
            )
    return checks


def verification_status(checks: list[ClaimCheck]) -> VerificationStatus:
    """Any unsupported claim makes the script unsupported; unread sources keep it in review."""
    if not checks:
        return VerificationStatus.needs_review
    if any(check.status == UNSUPPORTED for check in checks):
        return VerificationStatus.unsupported
    if any(check.status == UNVERIFIED for check in checks):
        return VerificationStatus.needs_review
    return VerificationStatus.supported


def build_report(claims: list[Claim], sources: list[FetchedSource]) -> VerificationReport:
    checks = check_claims(claims, sources)
    return VerificationReport(
        status=verification_status(checks),
        checks=checks,
        retrieved=sum(1 for source in sources if source.status == "ok"),
    )
