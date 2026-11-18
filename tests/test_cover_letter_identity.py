"""Cover-letter identity matching tolerates vendor casing, not the wrong employer."""

from applywright.application_packages.service import same_identity


def test_vendor_casing_is_accepted():
    """An import may serve 'Acmeco'; the letter should be free to say 'AcmeCo'."""
    assert same_identity("AcmeCo", "Acmeco")
    assert same_identity("WidgetNow", "Widgetnow")
    assert same_identity("SuccessMetric", "Successmetric")
    assert same_identity("ClickHouse", "Clickhouse")


def test_whitespace_differences_are_accepted():
    assert same_identity("Globex  Corp", "Globex Corp")
    assert same_identity(" Initech ", "Initech")


def test_a_different_company_still_fails():
    """The check exists to catch a letter addressed to the wrong employer."""
    assert not same_identity("Hooli Corporation", "Acmeco")
    assert not same_identity("AcmeCo Ltd", "Acmeco")
    assert not same_identity("", "Acmeco")


def test_a_different_role_still_fails():
    assert not same_identity(
        "Solution Architect, New Logo", "Senior Site Reliability Engineer"
    )
