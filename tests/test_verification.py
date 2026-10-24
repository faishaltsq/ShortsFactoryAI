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


def test_quote_without_citation_markers_matches_prose_that_has_them():
    """A correct quote must not be judged contradictory just because it omits [1]."""
    from packages.core.research.retrieval import FetchedSource
    from packages.core.research.verification import Claim, check_claims

    text = ("ELIZA is an early natural language processing computer program developed from 1964 to 1967 "
            "[ 1 ] at MIT by Joseph Weizenbaum . [ 2 ] [ 3 ] Created to explore communication.")
    quote = ("ELIZA is an early natural language processing computer program developed from 1964 to 1967 "
             "at MIT by Joseph Weizenbaum.")
    source = FetchedSource(url="https://example.com/eliza", status="ok", chars=len(text), text=text)

    [check] = check_claims([Claim(statement="ELIZA dibuat di MIT.", quote=quote,
                                 source_url=source.url)], [source])
    assert check.status == "supported", check.reason


def test_a_quote_absent_from_the_source_is_still_unsupported():
    from packages.core.research.retrieval import FetchedSource
    from packages.core.research.verification import Claim, check_claims

    text = "ELIZA is an early natural language processing computer program developed from 1964 to 1967."
    source = FetchedSource(url="https://example.com/eliza", status="ok", chars=len(text), text=text)
    [check] = check_claims([Claim(statement="ELIZA memenangkan Turing Award.",
                                 quote="ELIZA won the Turing Award in 1966.",
                                 source_url=source.url)], [source])
    assert check.status == "unsupported"


def test_an_elided_quote_must_still_be_present_in_order():
    """An ellipsis may hide source text but may never invent it."""
    from packages.core.research.retrieval import FetchedSource
    from packages.core.research.verification import Claim, check_claims

    text = ("The most famous script, DOCTOR, simulated a psychotherapist of the Rogerian school "
            "(in which the therapist reflects back words) and used rules dictated in the script "
            "to respond with non-directional questions to user inputs.")
    source = FetchedSource(url="https://example.com/eliza", status="ok", chars=len(text), text=text)
    quote = ("The most famous script, DOCTOR, simulated a psychotherapist of the Rogerian school ... "
             "and used rules dictated in the script to respond with non-directional questions")

    [ok] = check_claims([Claim(statement="DOCTOR meniru terapis Rogerian.",
                               quote=quote, source_url=source.url)], [source])
    assert ok.status == "supported", ok.reason

    [bad] = check_claims([Claim(statement="DOCTOR meniru terapis Rogerian.",
                                quote="The most famous script, DOCTOR, simulated a psychotherapist ... "
                                      "and won the 1966 Turing Award for non-directional questions",
                                source_url=source.url)], [source])
    assert bad.status == "unsupported", "an elision must not let invented text pass"


def test_an_elided_quote_keeps_fragments_in_source_order():
    from packages.core.research.retrieval import FetchedSource
    from packages.core.research.verification import Claim, check_claims

    text = "Alpha fragment appears first here and beta fragment appears later in the same page."
    source = FetchedSource(url="https://example.com/x", status="ok", chars=len(text), text=text)
    [check] = check_claims([Claim(statement="urutan", quote="beta fragment appears later ... Alpha fragment appears first",
                                  source_url=source.url)], [source])
    assert check.status == "unsupported", "reversed fragments are not the source's order"


def test_quote_without_maintenance_markers_matches_prose_that_has_them():
    """A verbatim quote that drops "[page needed]" is not invented text.

    Wikipedia interleaves maintenance templates into prose. The source sentence
    "attributed human-like feelings to the computer program, [ page needed ] a
    phenomenon..." is quoted by the model without the template; scoring that as
    unsupported makes every such citation fail the live approval gate.
    """
    text = ("He was surprised that some people, including his secretary, attributed human-like "
            "feelings to the computer program, [ page needed ] a phenomenon that came to be called "
            "the ELIZA effect .")
    source = _source(text)
    quote = ("He was surprised that some people, including his secretary, attributed human-like "
             "feelings to the computer program, a phenomenon that came to be called the ELIZA effect.")
    [check] = check_claims([_claim(quote)], [source])
    assert check.status == "supported", check.reason


def test_bracketed_words_the_source_asserts_are_not_stripped():
    """Only known maintenance templates are apparatus; arbitrary brackets are content."""
    text = "The report says [not a marker] that the panel efficiency reached 20 percent."
    source = _source(text)
    [check] = check_claims([_claim("The report says that the panel efficiency reached 20 percent.")], [source])
    assert check.status == "unsupported", "dropping an unknown bracketed phrase must not pass"
