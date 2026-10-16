import pytest

from servicenow_mcp.config import ConfigError, Settings, normalise_instance


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("dev12345", "https://dev12345.service-now.com"),
        ("dev12345.service-now.com", "https://dev12345.service-now.com"),
        ("https://dev12345.service-now.com", "https://dev12345.service-now.com"),
        ("https://dev12345.service-now.com/", "https://dev12345.service-now.com"),
        ("  dev12345  ", "https://dev12345.service-now.com"),
    ],
)
def test_instance_normalisation(raw, expected):
    assert normalise_instance(raw) == expected


def test_plain_http_is_refused():
    # Credentials must never go over an unencrypted channel.
    with pytest.raises(ConfigError, match="https"):
        normalise_instance("http://dev12345.service-now.com")


def test_empty_instance_is_refused():
    with pytest.raises(ConfigError):
        normalise_instance("   ")


def test_mock_mode_needs_no_instance(monkeypatch):
    monkeypatch.delenv("SN_INSTANCE", raising=False)
    monkeypatch.setenv("SN_AUTH_MODE", "mock")
    settings = Settings.from_env()
    assert settings.is_mock
    assert settings.instance_url == "https://mock.service-now.com"


def test_oauth_requires_client_credentials(monkeypatch):
    monkeypatch.setenv("SN_AUTH_MODE", "oauth")
    monkeypatch.setenv("SN_INSTANCE", "dev12345")
    monkeypatch.delenv("SN_CLIENT_ID", raising=False)
    monkeypatch.delenv("SN_CLIENT_SECRET", raising=False)
    with pytest.raises(ConfigError, match="SN_CLIENT_ID"):
        Settings.from_env()


def test_basic_requires_username_password(monkeypatch):
    monkeypatch.setenv("SN_AUTH_MODE", "basic")
    monkeypatch.setenv("SN_INSTANCE", "dev12345")
    monkeypatch.delenv("SN_USERNAME", raising=False)
    monkeypatch.delenv("SN_PASSWORD", raising=False)
    with pytest.raises(ConfigError, match="SN_USERNAME"):
        Settings.from_env()


def test_unknown_auth_mode_is_refused(monkeypatch):
    monkeypatch.setenv("SN_AUTH_MODE", "sso-magic")
    with pytest.raises(ConfigError, match="SN_AUTH_MODE"):
        Settings.from_env()


def test_non_mock_requires_instance(monkeypatch):
    monkeypatch.setenv("SN_AUTH_MODE", "basic")
    monkeypatch.delenv("SN_INSTANCE", raising=False)
    monkeypatch.setenv("SN_USERNAME", "u")
    monkeypatch.setenv("SN_PASSWORD", "p")
    with pytest.raises(ConfigError, match="SN_INSTANCE"):
        Settings.from_env()


def test_limits_are_clamped(monkeypatch):
    monkeypatch.setenv("SN_AUTH_MODE", "mock")
    monkeypatch.setenv("SN_MAX_LIMIT", "25")
    settings = Settings.from_env()
    assert settings.clamp_limit(None) == 10
    assert settings.clamp_limit(5) == 5
    assert settings.clamp_limit(9999) == 25  # capped
    assert settings.clamp_limit(0) == 1      # floored
    assert settings.clamp_limit(-7) == 1


def test_default_limit_cannot_exceed_max(monkeypatch):
    monkeypatch.setenv("SN_AUTH_MODE", "mock")
    monkeypatch.setenv("SN_MAX_LIMIT", "3")
    monkeypatch.setenv("SN_DEFAULT_LIMIT", "500")
    assert Settings.from_env().default_limit == 3


def test_table_allowlist_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("SN_AUTH_MODE", "mock")
    monkeypatch.setenv("SN_ALLOWED_TABLES", "incident, Sys_User")
    settings = Settings.from_env()
    assert settings.table_allowed("INCIDENT")
    assert settings.table_allowed("sys_user")
    assert not settings.table_allowed("sys_user_password")


def test_bad_integer_env_is_refused(monkeypatch):
    monkeypatch.setenv("SN_AUTH_MODE", "mock")
    monkeypatch.setenv("SN_MAX_LIMIT", "fifty")
    with pytest.raises(ConfigError, match="integer"):
        Settings.from_env()
