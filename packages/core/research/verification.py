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
# Wikipedia and most reference pages interleave bracketed citation markers into the
# prose. A model quoting the sentence correctly but omitting "[1]" would otherwise
# be judged as contradicting the source, which is the opposite of what happened.
# Inline maintenance templates ("[page needed]", "[better source needed]", "[who?]")
# are the same kind of editorial apparatus and must be stripped too; without them a
# verbatim quote that drops "[ page needed ]" is scored as invented text.
# The list stays explicit: stripping every bracketed phrase would also erase words
# the source actually asserts, which would hide fabricated quotes.
_MAINTENANCE = (
    "citation needed", "page needed", "better source needed", "additional citation needed",
    "full citation needed", "clarification needed", "verification needed", "failed verification",
    "not verified in body", "original research", "according to whom", "dead link",
    "permanent dead link", "unreliable source", "weasel words", "needs update", "needs page",
    "dubious", "disputed", "update", "sic", "quantify", "vague", "clarify",
    "who", "what", "when", "where", "why", "how",
)
_MAINTENANCE_RE = "|".join(r"\s+".join(re.escape(word) for word in template.split()) for template in _MAINTENANCE)
_CITATION = re.compile(rf"\[\s*(?:\d+|[a-z]|note\s*\d+|{_MAINTENANCE_RE})\s*\??\s*\]", re.IGNORECASE)
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
    """Casefold, drop citation markers and punctuation, collapse whitespace.

    This is the form used for matching, so a quote and the source text compare on
    prose alone: bracketed reference markers are editorial apparatus, not evidence.
    """
    return _WHITESPACE.sub(" ", _PUNCTUATION.sub(" ", _CITATION.sub(" ", text.casefold()))).strip()


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
        normalized_text = normalize(source.text)
        if normalized_quote in normalized_text:
            checks.append(ClaimCheck(statement, SUPPORTED, url, quote, matched=quote, reason="quote found"))
        elif _elided_match(quote, normalized_text):
            checks.append(ClaimCheck(statement, SUPPORTED, url, quote, matched=quote,
                                     reason="quote found across an elision"))
        else:
            checks.append(
                ClaimCheck(statement, UNSUPPORTED, url, quote, reason="quote not found in retrieved text")
            )
    return checks


_ELISION = re.compile(r"\s*(?:\.{3,}|…)\s*")


def _elided_match(quote: str, normalized_text: str) -> bool:
    """A quote joined with an ellipsis is several fragments, each of which must appear.

    Models elide a clause and join two passages, which is legitimate citation
    practice. Every fragment still has to be present, in order, in the source:
    an ellipsis may hide text but may never invent it. The quote is split before
    normalization, because normalization erases the ellipsis itself.
    """
    fragments = [normalize(fragment) for fragment in _ELISION.split(quote)]
    fragments = [fragment for fragment in fragments if fragment]
    if len(fragments) < 2 or any(len(fragment) < MIN_QUOTE_CHARS // 2 for fragment in fragments):
        return False
    cursor = 0
    for fragment in fragments:
        found = normalized_text.find(fragment, cursor)
        if found < 0:
            return False
        cursor = found + len(fragment)
    return True


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
