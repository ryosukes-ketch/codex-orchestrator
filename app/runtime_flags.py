TRUTHY_TOKENS = {"1", "true", "yes", "on"}
FALSY_TOKENS = {"0", "false", "no", "off"}


def parse_env_bool(value: str | None, *, default: bool) -> bool:
    normalized = (value or "").strip().lower()
    if normalized in TRUTHY_TOKENS:
        return True
    if normalized in FALSY_TOKENS:
        return False
    return default


def parse_strict_env_flag(value: str | None) -> bool:
    normalized = (value or "").strip()
    if not normalized:
        return False
    # Malformed strict flags fail-safe to strict mode.
    return parse_env_bool(normalized, default=True)
