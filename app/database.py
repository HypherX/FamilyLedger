"""SQLite。引擎在第一次使用时按当前资料目录打开。"""
import logging
import os
from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from . import paths

logger = logging.getLogger("familyledger")

_engine = None
_factory = None


class Base(DeclarativeBase):
    pass


def _connect(dbapi_conn, _connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def get_engine():
    global _engine, _factory
    if _engine is None:
        folder = paths.data_dir()
        os.makedirs(folder, exist_ok=True)
        url = "sqlite:///" + str(folder / "ledger.db")
        _engine = create_engine(url, connect_args={"check_same_thread": False}, future=True)
        event.listen(_engine, "connect", _connect)
        _factory = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False, future=True)
        logger.info("账本数据库：%s", folder / "ledger.db")
    return _engine


def open_session() -> Session:
    get_engine()
    return _factory()


def get_db() -> Iterator[Session]:
    db = open_session()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models
    from .settings_store import seed

    Base.metadata.create_all(get_engine())
    with open_session() as db:
        seed(db)
        for row in db.query(models.ImportBatch).filter(models.ImportBatch.status == "running"):
            row.status = "error"
            row.error = "上次导入中断了，请再试一次"
        db.commit()
