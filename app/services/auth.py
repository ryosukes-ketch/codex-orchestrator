import os
from functools import lru_cache

from app.runtime_flags import parse_env_bool
from app.schemas.project import ActorContext, ActorRole, ActorType


class AuthenticationError(Exception):
    pass


def _default_token_map() -> dict[str, ActorContext]:
    return {
        "dev-owner-token": ActorContext(
            actor_id="owner-1",
            actor_role=ActorRole.OWNER,
            actor_type=ActorType.HUMAN,
        ),
        "dev-operator-token": ActorContext(
            actor_id="operator-1",
            actor_role=ActorRole.OPERATOR,
            actor_type=ActorType.HUMAN,
        ),
        "dev-approver-token": ActorContext(
            actor_id="approver-1",
            actor_role=ActorRole.APPROVER,
            actor_type=ActorType.HUMAN,
        ),
        "dev-admin-token": ActorContext(
            actor_id="admin-1",
            actor_role=ActorRole.ADMIN,
            actor_type=ActorType.HUMAN,
        ),
        "dev-viewer-token": ActorContext(
            actor_id="viewer-1",
            actor_role=ActorRole.VIEWER,
            actor_type=ActorType.HUMAN,
        ),
    }


def _parse_token_seed(seed: str | None) -> dict[str, ActorContext]:
    if not seed:
        return _default_token_map()
    mapping: dict[str, ActorContext] = {}
    # Format:
    # token:actor_id:actor_role:actor_type,token2:actor_id2:actor_role2:actor_type2
    for item in seed.split(","):
        raw = item.strip()
        if not raw:
            continue
        parts = [part.strip() for part in raw.split(":")]
        if len(parts) != 4:
            continue
        token, actor_id, actor_role, actor_type = parts
        if not token or not actor_id:
            continue
        try:
            parsed_role = ActorRole(actor_role.lower())
            parsed_type = ActorType(actor_type.lower())
        except ValueError:
            continue
        mapping[token] = ActorContext(
            actor_id=actor_id,
            actor_role=parsed_role,
            actor_type=parsed_type,
        )
    return mapping or _default_token_map()


class DevTokenAuthService:
    def __init__(self, token_map: dict[str, ActorContext], enabled: bool = True) -> None:
        self.token_map = token_map
        self.enabled = enabled

    def resolve_actor(self, authorization_header: str | None) -> ActorContext:
        if not self.enabled:
            return ActorContext(
                actor_id="auth-disabled",
                actor_role=ActorRole.ADMIN,
                actor_type=ActorType.SYSTEM,
            )

        if not authorization_header:
            raise AuthenticationError("Missing Authorization header.")

        parts = authorization_header.strip().split(None, 1)
        if len(parts) != 2:
            raise AuthenticationError("Authorization must be Bearer token.")
        scheme, token = parts[0], parts[1].strip()
        if scheme.lower() != "bearer" or not token:
            raise AuthenticationError("Authorization must be Bearer token.")

        actor = self.token_map.get(token)
        if not actor:
            raise AuthenticationError("Invalid bearer token.")
        return actor


def _parse_bool_with_default(value: str | None, *, default: bool) -> bool:
    return parse_env_bool(value, default=default)


@lru_cache(maxsize=1)
def get_auth_service() -> DevTokenAuthService:
    token_seed = os.getenv("DEV_AUTH_TOKEN_SEED", "").strip()
    enabled = _parse_bool_with_default(os.getenv("DEV_AUTH_ENABLED"), default=True)
    return DevTokenAuthService(
        token_map=_parse_token_seed(token_seed),
        enabled=enabled,
    )
