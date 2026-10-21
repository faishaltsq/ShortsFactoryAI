from packages.core.research import Claim, VerificationReport, build_report, check_claims, normalize, verification_status
from packages.core.research.retrieval import FetchedSource
from packages.core.schemas import VerificationStatus

URL = "https://example.com/panel-efficiency"


def _source(text: str, status: str = "ok") -> FetchedSource:
    return FetchedSource(url=URL, status=status, chars=len(text), text=text)


def _claim(quote: str, url: str = URL) -> Claim:
    return Claim(statement="panel efficiency claim", quote=quote, source_url=url)


def test_normalize_casefolds_and_drops_punctuation():
    assert normalize("  Cahaya, MATAHARI! ") == "cahaya matahari"


def test_quote_found_in_source_counts_as_supported():
    source = _source("Modern panels convert about 20% of sunlight into electricity.")
    [check] = check_claims([_claim("about 20% of sunlight into electricity")], [source])
    assert check.status == "supported"
    assert check.matched
    assert verification_status([check]) == "supported"


def test_matching_ignores_case_punctuation_and_spacing():
    source = _source("The  International  Space Station orbits at ~408 km.")
    [check] = check_claims([_claim("International Space Station orbits at 408 km")], [source])
    assert check.status == "supported"


def test_absent_quote_is_unsupported_not_unverified():
    source = _source("Modern panels convert about 20% of sunlight.")
    [check] = check_claims([_claim("panels reach 97% efficiency")], [source])
    assert check.status == "unsupported"
    assert "not found" in check.reason
    assert verification_status([check]) == "unsupported"


def test_missing_source_is_unverified():
    [check] = check_claims([_claim("some quote long enough to check")], [])
    assert check.status == "unverified"
    assert "not retrieved" in check.reason


def test_failed_fetch_is_unverified_even_with_a_quote():
    source = _source("any text", status="http_500")
    [check] = check_claims([_claim("some quote long enough to check")], [source])
    assert check.status == "unverified"


def test_too_short_quote_cannot_be_checked():
    source = _source("Long page of retrieved text.")
    [check] = check_claims([_claim("ok")], [source])
    assert check.status == "unverified"
    assert "shorter than" in check.reason


def test_one_unsupported_claim_makes_the_whole_script_unsupported():
    source = _source("One true sentence about solar panels here.")
    checks = check_claims(
        [_claim("One true sentence about solar"), _claim("a claim the page never states")],
        [source],
    )
    assert verification_status(checks) == "unsupported"


def test_unread_sources_keep_the_script_in_review():
    report = build_report([_claim("some quote long enough to check")], [])
    assert isinstance(report, VerificationReport)
    assert report.status.value == "needs_review"
    assert report.retrieved == 0
    assert len(report.unverified) == 1


def test_no_claims_needs_review():
    assert verification_status([]) is VerificationStatus.needs_review
