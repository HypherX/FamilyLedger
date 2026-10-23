import json
import os

from sqlalchemy.orm import Session

from . import paths
from .llm import LLMSettings
from .models import Setting

_KEYS = ("base_url", "api_key", "model", "household_name")


def _get(db: Session, key: str, default: str = "") -> str:
    row = db.get(Setting, key)
    return row.value if row else default


def seed(db: Session) -> None:
    if db.get(Setting, "base_url") or db.get(Setting, "household_name"):
        if not db.get(Setting, "household_name"):
            db.add(Setting(key="household_name", value="家庭账本"))
            db.commit()
        return
    payload = {}
    if not os.environ.get("FAMILYLEDGER_SKIP_SECRETS"):
        secret = paths.secrets_path()
        if secret is not None:
            try:
                payload = json.loads(secret.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}
    for key in ("base_url", "api_key", "model"):
        value = str(payload.get(key) or "").strip()
        if value:
            db.add(Setting(key=key, value=value))
    db.add(Setting(key="household_name", value=str(payload.get("household_name") or "家庭账本")))
    db.commit()


def llm_settings(db: Session) -> LLMSettings:
    return LLMSettings(
        base_url=_get(db, "base_url"),
        api_key=_get(db, "api_key"),
        model=_get(db, "model"),
    )


def mask_key(value: str) -> str:
    text = value.strip()
    if len(text) < 8:
        return ""
    return text[:3] + "…" + text[-4:]


def public_settings(db: Session) -> dict:
    key = _get(db, "api_key")
    return {
        "base_url": _get(db, "base_url"),
        "model": _get(db, "model"),
        "household_name": _get(db, "household_name") or "家庭账本",
        "api_key_set": bool(key.strip()),
        "api_key_hint": mask_key(key),
    }


def update_settings(db: Session, patch: dict) -> None:
    for key in _KEYS:
        if key not in patch or patch[key] is None:
            continue
        text = str(patch[key]).strip()
        if key == "api_key" and not text:
            continue
        if key in {"base_url", "model"} and not text:
            continue
        row = db.get(Setting, key)
        if row is None:
            db.add(Setting(key=key, value=text))
        else:
            row.value = text
    db.commit()
