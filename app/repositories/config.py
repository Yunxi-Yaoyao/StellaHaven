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


def bump_monitors_version(db: Session, *, commit: bool = True) -> int:
    """Atomic database increment, independent of stale ORM identity-map values.

    The caller's definition changes and this version share one transaction.
    PostgreSQL ON CONFLICT also serializes writers using different domain locks.
    """
    from sqlalchemy import cast, Integer, String
    if db.get_bind().dialect.name == 'sqlite':
        from sqlalchemy.dialects.sqlite import insert
    else:
        from sqlalchemy.dialects.postgresql import insert
    statement = insert(AppConfig).values(key='monitors_version', value='1')
    statement = statement.on_conflict_do_update(index_elements=['key'],
        set_={'value': cast(cast(AppConfig.value, Integer) + 1, String)}).returning(AppConfig.value)
    value = int(db.execute(statement).scalar_one())
    if commit:
        db.commit()
    return value
