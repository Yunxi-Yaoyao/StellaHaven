"""全局配置 repositories：key-value 读写 + 监控版本号。"""
from sqlalchemy.orm import Session

from app.models.config import AppConfig


def get(db: Session, key: str, default: str | None = None) -> str | None:
    row = db.get(AppConfig, key)
    return row.value if row else default


def put(db: Session, key: str, value: str) -> None:
    row = db.get(AppConfig, key)
    if row:
        row.value = value
    else:
        db.add(AppConfig(key=key, value=value))
    db.commit()


def get_monitors_version(db: Session) -> int:
    try:
        return int(get(db, "monitors_version", "0") or "0")
    except (TypeError, ValueError):
        return 0


def bump_monitors_version(db: Session) -> int:
    v = get_monitors_version(db) + 1
    put(db, "monitors_version", str(v))
    return v
