import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any, Protocol

from app.runtime_flags import parse_env_bool
from app.schemas.project import ActorContext, ActorRole, ActorType


class AuthenticationError(Exception):
    pass


class AuthService(Protocol):
    def resolve_actor(self, authorization_header: str | None) -> ActorContext: ...


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _token_preview(token: str) -> str:
    if len(token) <= 8:
        return token
    return f"{token[:4]}...{token[-4:]}"


def _token_fingerprint(token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return digest[:16]


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


def _parse_token_seed(seed: str | None, *, fallback_to_default: bool = True) -> dict[str, ActorContext]:
    if not seed:
        return _default_token_map() if fallback_to_default else {}
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
    if mapping:
        return mapping
    return _default_token_map() if fallback_to_default else {}


class TokenMapAuthService:
    def __init__(
        self,
        token_map: dict[str, ActorContext],
        enabled: bool = True,
        *,
        service_mode: str = "token_map",
    ) -> None:
        self.token_map = token_map
        self.enabled = enabled
        self.service_mode = service_mode

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

    @property
    def token_store_path(self) -> str:
        return ""


class DevTokenAuthService(TokenMapAuthService):
    def __init__(self, token_map: dict[str, ActorContext], enabled: bool = True) -> None:
        super().__init__(token_map=token_map, enabled=enabled, service_mode="dev_token")


class CommercialTokenAuthService(TokenMapAuthService):
    def __init__(
        self,
        token_map: dict[str, ActorContext],
        enabled: bool = True,
        *,
        token_store_path: str | None = None,
    ) -> None:
        super().__init__(token_map=token_map, enabled=enabled, service_mode="commercial_token")
        self._seed_token_map = dict(token_map)
        self._lock = Lock()
        self._token_store_path = token_store_path.strip() if token_store_path else ""
        self._token_metadata: dict[str, dict[str, str]] = {
            token: {
                "created_at": _utc_now_iso(),
                "updated_at": _utc_now_iso(),
                "description": "",
            }
            for token in self.token_map
        }
        self._load_from_store_if_available()
        self._apply_seed_tokens()
        self._save_to_store()

    @property
    def token_store_path(self) -> str:
        return self._token_store_path

    def list_token_descriptors(self) -> list[dict[str, str]]:
        with self._lock:
            descriptors: list[dict[str, str]] = []
            for token, actor in sorted(
                self.token_map.items(),
                key=lambda item: (item[1].actor_role.value, item[1].actor_id, item[0]),
            ):
                metadata = self._token_metadata.get(token, {})
                descriptors.append(
                    {
                        "token_preview": _token_preview(token),
                        "token_fingerprint": _token_fingerprint(token),
                        "actor_id": actor.actor_id,
                        "actor_role": actor.actor_role.value,
                        "actor_type": actor.actor_type.value,
                        "created_at": metadata.get("created_at", ""),
                        "updated_at": metadata.get("updated_at", ""),
                        "description": metadata.get("description", ""),
                    }
                )
            return descriptors

    def issue_token(
        self,
        *,
        actor_id: str,
        actor_role: ActorRole,
        actor_type: ActorType,
        description: str = "",
        token: str | None = None,
    ) -> dict[str, Any]:
        generated_token = (token or "").strip() or secrets.token_urlsafe(32)
        with self._lock:
            if generated_token in self.token_map:
                raise ValueError("Token already exists.")

            actor = ActorContext(
                actor_id=actor_id.strip(),
                actor_role=actor_role,
                actor_type=actor_type,
            )
            now = _utc_now_iso()
            self.token_map[generated_token] = actor
            self._token_metadata[generated_token] = {
                "created_at": now,
                "updated_at": now,
                "description": description.strip(),
            }
            self._save_to_store()
            metadata = self._token_metadata[generated_token]
            return {
                "token": generated_token,
                "token_preview": _token_preview(generated_token),
                "token_fingerprint": _token_fingerprint(generated_token),
                "actor": actor,
                "created_at": metadata.get("created_at", ""),
                "updated_at": metadata.get("updated_at", ""),
                "description": metadata.get("description", ""),
            }

    def revoke_token(self, *, token: str) -> dict[str, Any]:
        target = token.strip()
        with self._lock:
            actor = self.token_map.pop(target, None)
            metadata = self._token_metadata.pop(target, {})
            if actor is None:
                raise LookupError("Token not found.")
            self._save_to_store()
            return {
                "token_preview": _token_preview(target),
                "token_fingerprint": _token_fingerprint(target),
                "actor": actor,
                "created_at": metadata.get("created_at", ""),
                "updated_at": metadata.get("updated_at", ""),
                "description": metadata.get("description", ""),
                "revoked_at": _utc_now_iso(),
            }

    def rotate_token(self, *, token: str, new_token: str | None = None) -> dict[str, Any]:
        target = token.strip()
        replacement = (new_token or "").strip() or secrets.token_urlsafe(32)
        with self._lock:
            actor = self.token_map.get(target)
            if actor is None:
                raise LookupError("Token not found.")
            if replacement != target and replacement in self.token_map:
                raise ValueError("Replacement token already exists.")

            existing_metadata = dict(self._token_metadata.get(target, {}))
            if not existing_metadata.get("created_at"):
                existing_metadata["created_at"] = _utc_now_iso()
            existing_metadata["updated_at"] = _utc_now_iso()
            self.token_map.pop(target, None)
            self._token_metadata.pop(target, None)
            self.token_map[replacement] = actor
            self._token_metadata[replacement] = existing_metadata
            self._save_to_store()
            return {
                "old_token_preview": _token_preview(target),
                "old_token_fingerprint": _token_fingerprint(target),
                "token": replacement,
                "token_preview": _token_preview(replacement),
                "token_fingerprint": _token_fingerprint(replacement),
                "actor": actor,
                "created_at": existing_metadata.get("created_at", ""),
                "updated_at": existing_metadata.get("updated_at", ""),
                "description": existing_metadata.get("description", ""),
            }

    def _load_from_store_if_available(self) -> None:
        if not self._token_store_path:
            return
        store_path = Path(self._token_store_path).expanduser()
        if not store_path.exists():
            return
        try:
            raw = json.loads(store_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            return
        loaded_token_map: dict[str, ActorContext] = {}
        loaded_metadata: dict[str, dict[str, str]] = {}
        for item in raw.get("tokens", []):
            if not isinstance(item, dict):
                continue
            token = str(item.get("token", "")).strip()
            actor_id = str(item.get("actor_id", "")).strip()
            role_raw = str(item.get("actor_role", "")).strip().lower()
            type_raw = str(item.get("actor_type", "")).strip().lower()
            if not token or not actor_id:
                continue
            try:
                actor_role = ActorRole(role_raw)
                actor_type = ActorType(type_raw)
            except ValueError:
                continue
            loaded_token_map[token] = ActorContext(
                actor_id=actor_id,
                actor_role=actor_role,
                actor_type=actor_type,
            )
            loaded_metadata[token] = {
                "created_at": str(item.get("created_at", "")).strip() or _utc_now_iso(),
                "updated_at": str(item.get("updated_at", "")).strip() or _utc_now_iso(),
                "description": str(item.get("description", "")).strip(),
            }

        if loaded_token_map:
            self.token_map = loaded_token_map
            self._token_metadata = loaded_metadata

    def _apply_seed_tokens(self) -> None:
        if not self._seed_token_map:
            return
        now = _utc_now_iso()
        for token, actor in self._seed_token_map.items():
            existing_metadata = self._token_metadata.get(token, {})
            created_at = existing_metadata.get("created_at", "") or now
            updated_at = existing_metadata.get("updated_at", "") or now
            description = existing_metadata.get("description", "")
            self.token_map[token] = actor
            self._token_metadata[token] = {
                "created_at": created_at,
                "updated_at": updated_at,
                "description": description,
            }

    def _save_to_store(self) -> None:
        if not self._token_store_path:
            return
        store_path = Path(self._token_store_path).expanduser()
        store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "updated_at": _utc_now_iso(),
            "tokens": [],
        }
        for token, actor in sorted(self.token_map.items(), key=lambda item: item[0]):
            metadata = self._token_metadata.get(token, {})
            payload["tokens"].append(
                {
                    "token": token,
                    "actor_id": actor.actor_id,
                    "actor_role": actor.actor_role.value,
                    "actor_type": actor.actor_type.value,
                    "created_at": metadata.get("created_at", ""),
                    "updated_at": metadata.get("updated_at", ""),
                    "description": metadata.get("description", ""),
                }
            )
        store_path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )


def _parse_bool_with_default(value: str | None, *, default: bool) -> bool:
    return parse_env_bool(value, default=default)


@lru_cache(maxsize=1)
def get_auth_service() -> AuthService:
    auth_mode = os.getenv("AUTH_SERVICE_MODE", "dev_token").strip().lower()
    if auth_mode in {"commercial_token", "token_map", "commercial"}:
        token_seed = os.getenv("AUTH_TOKEN_SEED", "").strip()
        token_store_path = os.getenv("AUTH_TOKEN_STORE_PATH", "").strip()
        if not token_store_path:
            token_store_path = "logs/auth/commercial-token-store.json"
        enabled = _parse_bool_with_default(os.getenv("AUTH_ENABLED"), default=True)
        return CommercialTokenAuthService(
            token_map=_parse_token_seed(token_seed, fallback_to_default=False),
            enabled=enabled,
            token_store_path=token_store_path,
        )

    token_seed = os.getenv("DEV_AUTH_TOKEN_SEED", "").strip()
    enabled = _parse_bool_with_default(os.getenv("DEV_AUTH_ENABLED"), default=True)
    return DevTokenAuthService(
        token_map=_parse_token_seed(token_seed),
        enabled=enabled,
    )
