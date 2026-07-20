from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from api.config import DATABASE_URL, DATA_DIR, REPORTS_DIR


class Base(DeclarativeBase):
    pass


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _migrate_legacy_sessions() -> None:
    """Phase 1 -> Phase 2: drop anonymous sessions without user_id."""
    inspector = inspect(engine)
    if "chat_sessions" not in inspector.get_table_names():
        return

    columns = {col["name"] for col in inspector.get_columns("chat_sessions")}
    if "user_id" in columns:
        return

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS analysis_snapshots"))
        conn.execute(text("DROP TABLE IF EXISTS chat_messages"))
        conn.execute(text("DROP TABLE IF EXISTS chat_sessions"))


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    from api.db import models  # noqa: F401

    _migrate_legacy_sessions()
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
