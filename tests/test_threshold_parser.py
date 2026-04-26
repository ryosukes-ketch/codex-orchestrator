from __future__ import annotations

from app.domain.enums import ReleaseType
from app.services.actual_parser import ActualParserService
from app.utils.parsing import parse_contract_threshold


def test_threshold_parser_above_percent() -> None:
    threshold = parse_contract_threshold("Will CPI be above 3.1% in April?")
    assert threshold is not None
    assert threshold.comparator == "above"
    assert threshold.value == 3.1


def test_threshold_parser_below_k() -> None:
    threshold = parse_contract_threshold("Payrolls below 150k")
    assert threshold is not None
    assert threshold.comparator == "below"
    assert threshold.value == 150_000


def test_actual_parser_cpi(fixtures_dir) -> None:
    parser = ActualParserService()
    html = (fixtures_dir / "bls_cpi_release.html").read_text(encoding="utf-8")
    parsed = parser.parse(ReleaseType.CPI, html)
    assert parsed.actual_value_num == 3.3


def test_actual_parser_nfp(fixtures_dir) -> None:
    parser = ActualParserService()
    html = (fixtures_dir / "bls_nfp_release.html").read_text(encoding="utf-8")
    parsed = parser.parse(ReleaseType.NFP, html)
    assert parsed.actual_value_num == 120_000.0


def test_actual_parser_fomc_ignores_non_decision_raised_language() -> None:
    parser = ActualParserService()
    content = (
        "The Committee raised concerns about inflation persistence. "
        "The Committee decided to maintain the target range for the federal funds rate at 4.25 to 4.50 percent."
    )
    parsed = parser.parse(ReleaseType.FOMC, content)
    assert parsed.parsed_payload_json["decision_classification"] == "HOLD"


def test_actual_parser_fomc_hike_phrase_detected() -> None:
    parser = ActualParserService()
    content = "The Committee decided to raise the target range for the federal funds rate to 5.25 to 5.50 percent."
    parsed = parser.parse(ReleaseType.FOMC, content)
    assert parsed.parsed_payload_json["decision_classification"] == "HIKE"
