"""Settings parsing, URL normalisation and the guardrail predicates."""

import pytest

from sharepoint_policy_mcp.config import (
    DEFAULT_ALLOWED_LIBRARIES,
    ConfigError,
    Settings,
    normalise_site_url,
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in list(__import__("os").environ):
        if key.startswith("SP_"):
            monkeypatch.delenv(key, raising=False)


def test_defaults_to_mock_without_a_site():
    settings = Settings.from_env()
    assert settings.auth_mode == "mock"
    assert settings.is_mock is True
    assert settings.site_url.startswith("https://")
    assert settings.allowed_libraries == DEFAULT_ALLOWED_LIBRARIES


def test_unknown_auth_mode_is_rejected(monkeypatch):
    monkeypatch.setenv("SP_AUTH_MODE", "sorcery")
    with pytest.raises(ConfigError, match="SP_AUTH_MODE"):
        Settings.from_env()


def test_graph_mode_requires_a_site(monkeypatch):
    monkeypatch.setenv("SP_AUTH_MODE", "graph")
    with pytest.raises(ConfigError, match="SP_SITE_URL is required"):
        Settings.from_env()


def test_graph_mode_requires_all_three_credentials(monkeypatch):
    monkeypatch.setenv("SP_AUTH_MODE", "graph")
    monkeypatch.setenv("SP_SITE_URL", "contoso/sites/aml")
    monkeypatch.setenv("SP_TENANT_ID", "tenant")
    monkeypatch.setenv("SP_CLIENT_ID", "client")
    with pytest.raises(ConfigError, match="SP_CLIENT_SECRET"):
        Settings.from_env()


def test_graph_mode_accepts_a_complete_configuration(monkeypatch):
    monkeypatch.setenv("SP_AUTH_MODE", "graph")
    monkeypatch.setenv("SP_SITE_URL", "contoso/sites/aml")
    monkeypatch.setenv("SP_TENANT_ID", "tenant")
    monkeypatch.setenv("SP_CLIENT_ID", "client")
    monkeypatch.setenv("SP_CLIENT_SECRET", "secret")
    settings = Settings.from_env()
    assert settings.is_mock is False
    assert settings.site_url == "https://contoso.sharepoint.com/sites/aml"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("contoso/sites/aml", "https://contoso.sharepoint.com/sites/aml"),
        ("contoso.sharepoint.com/sites/aml", "https://contoso.sharepoint.com/sites/aml"),
        ("https://contoso.sharepoint.com/sites/aml/", "https://contoso.sharepoint.com/sites/aml"),
        ("  contoso/sites/aml  ", "https://contoso.sharepoint.com/sites/aml"),
    ],
)
def test_site_url_shapes_normalise(raw, expected):
    assert normalise_site_url(raw) == expected


def test_http_site_url_is_refused():
    with pytest.raises(ConfigError, match="https"):
        normalise_site_url("http://contoso.sharepoint.com/sites/aml")


def test_empty_site_url_is_refused():
    with pytest.raises(ConfigError, match="empty"):
        normalise_site_url("   ")


def test_limits_are_clamped(monkeypatch):
    monkeypatch.setenv("SP_MAX_LIMIT", "4")
    monkeypatch.setenv("SP_DEFAULT_LIMIT", "99")
    settings = Settings.from_env()
    # A default above the ceiling is pulled down to it rather than ignored.
    assert settings.default_limit == 4
    assert settings.clamp_limit(None) == 4
    assert settings.clamp_limit(100) == 4
    assert settings.clamp_limit(0) == 1
    assert settings.clamp_limit(2) == 2


def test_max_limit_must_be_positive(monkeypatch):
    monkeypatch.setenv("SP_MAX_LIMIT", "0")
    with pytest.raises(ConfigError, match="at least 1"):
        Settings.from_env()


def test_non_integer_limit_is_reported(monkeypatch):
    monkeypatch.setenv("SP_MAX_LIMIT", "lots")
    with pytest.raises(ConfigError, match="must be an integer"):
        Settings.from_env()


def test_passage_budget_has_a_floor(monkeypatch):
    monkeypatch.setenv("SP_MAX_PASSAGE_CHARS", "10")
    with pytest.raises(ConfigError, match="at least 200"):
        Settings.from_env()


def test_library_allowlist_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("SP_ALLOWED_LIBRARIES", "BSA Policies, QC Policies")
    settings = Settings.from_env()
    assert settings.library_allowed("bsa policies") is True
    assert settings.library_allowed("QC Policies") is True
    assert settings.library_allowed("QA Policies") is False


def test_empty_audience_is_readable_by_anyone():
    settings = Settings.from_env()
    assert settings.may_read(()) is True


def test_audience_needs_one_matching_group(monkeypatch):
    monkeypatch.setenv("SP_USER_GROUPS", "aml-analyst")
    settings = Settings.from_env()
    assert settings.may_read(("aml-manager", "bsa-officer")) is False
    assert settings.may_read(("aml-analyst",)) is True
    assert settings.may_read(("AML-Analyst",)) is True


def test_default_groups_are_least_privileged():
    # A misconfiguration should withhold a document, not disclose one.
    settings = Settings.from_env()
    assert settings.may_read(("bsa-officer",)) is False


def test_redaction_is_on_by_default_and_can_be_turned_off(monkeypatch):
    assert Settings.from_env().redact is True
    monkeypatch.setenv("SP_REDACT", "false")
    assert Settings.from_env().redact is False
