import pytest

from app.runtime_flags import parse_env_bool, parse_strict_env_flag


@pytest.mark.parametrize("raw", ["1", "true", "yes", "on", " TRUE "])
def test_parse_env_bool_accepts_truthy_tokens(raw: str) -> None:
    assert parse_env_bool(raw, default=False) is True


@pytest.mark.parametrize("raw", ["0", "false", "off", " no "])
def test_parse_env_bool_accepts_falsy_tokens(raw: str) -> None:
    assert parse_env_bool(raw, default=True) is False


@pytest.mark.parametrize("raw", [None, "", "invalid", "maybe"])
def test_parse_env_bool_uses_default_for_unknown_values(raw: str | None) -> None:
    assert parse_env_bool(raw, default=True) is True
    assert parse_env_bool(raw, default=False) is False


@pytest.mark.parametrize("raw", [None, "", "   ", "0", "false", "off", " no "])
def test_parse_strict_env_flag_handles_unset_and_false_tokens(raw: str | None) -> None:
    assert parse_strict_env_flag(raw) is False


@pytest.mark.parametrize("raw", ["1", "true", "yes", "on", " TRUE ", "invalid", "2"])
def test_parse_strict_env_flag_fails_safe_to_true_for_truthy_or_malformed_values(raw: str) -> None:
    assert parse_strict_env_flag(raw) is True
