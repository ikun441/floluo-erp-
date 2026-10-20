from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from .models import Gate


def make_engine(url):
    options = {"check_same_thread": False, "timeout": 30} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=options, pool_pre_ping=True, hide_parameters=True)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def foreign_keys(conn, _):
            conn.execute("PRAGMA foreign_keys=ON")

    return engine


def lock_gate(db: Session):
    if db.bind.dialect.name == "sqlite":
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        gate = db.get(Gate, 1)
    else:
        gate = db.scalar(select(Gate).where(Gate.id == 1).with_for_update())
    if gate is None:
        raise RuntimeError("Database not initialized: run migrations and bootstrap")
    return gate
