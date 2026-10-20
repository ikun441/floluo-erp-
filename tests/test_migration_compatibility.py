import json
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from erp.audit import append, digest, verify
from erp.database import lock_gate, make_engine
from erp.models import AuditEvent, Product
from sqlalchemy import MetaData, Table, create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


@pytest.mark.parametrize(
    "dialect", ["sqlite"] + (["postgresql"] if os.getenv("TEST_POSTGRES_URL") else [])
)
def test_existing_catalog_and_legacy_audit_survive_upgrade(tmp_path, monkeypatch, dialect):
    external = None
    schema = None
    url = "sqlite:///" + str(tmp_path / "legacy.db")
    if dialect == "postgresql":
        external = create_engine(os.environ["TEST_POSTGRES_URL"])
        schema = "erp_legacy_" + uuid4().hex
        with external.begin() as connection:
            connection.execute(text("CREATE SCHEMA " + schema))
        url = (
            make_url(os.environ["TEST_POSTGRES_URL"])
            .update_query_dict({"options": "-csearch_path=" + schema})
            .render_as_string(hide_password=False)
        )
    monkeypatch.setenv("DATABASE_URL", url)
    engine = create_engine(url)
    try:
        command.upgrade(Config("alembic.ini"), "724dfa42fcdd")
        when = datetime(2026, 1, 2, 3, 4, 5, 123456, tzinfo=UTC)
        parts = [None, "legacy-trace", "legacy-event", 200, "2026-01-02T03:04:05.123456", "0" * 64]
        legacy_hash = digest(json.dumps(parts, ensure_ascii=False, separators=(",", ":")))
        metadata = MetaData()
        users = Table("erp_user", metadata, autoload_with=engine)
        products = Table("product", metadata, autoload_with=engine)
        audits = Table("audit_event", metadata, autoload_with=engine)
        with engine.begin() as connection:
            connection.execute(
                users.insert().values(
                    id="legacy-user",
                    username="legacy-user",
                    password_hash="non-login-fixture",
                    active=True,
                    failed_logins=0,
                    created_at=when,
                    updated_at=when,
                    version=1,
                )
            )
            connection.execute(
                products.insert().values(
                    id="legacy-product",
                    sku="legacy-sku",
                    name="legacy-product",
                    unit="piece",
                    owner_id="legacy-user",
                    active=True,
                    created_at=when,
                    updated_at=when,
                    version=1,
                )
            )
            connection.execute(
                audits.insert().values(
                    actor_id=None,
                    trace_id="legacy-trace",
                    event="legacy-event",
                    result=200,
                    created_at=when,
                    previous_hash="0" * 64,
                    digest=legacy_hash,
                )
            )
        command.upgrade(Config("alembic.ini"), "head")
        with Session(engine) as db:
            assert db.get(Product, "legacy-product").category_id is None
            row = db.scalar(select(AuditEvent))
            assert row.format_version == 1 and row.digest == legacy_hash and verify(db)
            settings = db.execute(
                text('SELECT "values" FROM system_configuration WHERE id=1')
            ).scalar_one()
            if isinstance(settings, str):
                settings = json.loads(settings)
            assert settings == {
                "supported_currencies": [],
                "tax_mode": "unconfigured",
                "require_separate_approver": True,
            }
        # Empty new business schema is reversible; existing product/audit must remain intact.
        command.downgrade(Config("alembic.ini"), "724dfa42fcdd")
        assert "category_id" not in {c["name"] for c in inspect(engine).get_columns("product")}
        command.upgrade(Config("alembic.ini"), "head")
        checked_engine = make_engine(url)
        try:
            with Session(checked_engine) as db:
                lock_gate(db)
                append(db, None, "v2-trace", "v2-event", 200, {"changed_fields": ["name"]})
                db.commit()
                assert verify(db)
                assert (
                    db.scalar(select(AuditEvent.digest).where(AuditEvent.format_version == 1))
                    == legacy_hash
                )
            with pytest.raises(RuntimeError, match="Audit v2 records"):
                command.downgrade(Config("alembic.ini"), "724dfa42fcdd")
            if dialect == "sqlite":
                with checked_engine.connect() as connection:
                    assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
        finally:
            checked_engine.dispose()
    finally:
        engine.dispose()
        if external:
            with external.begin() as connection:
                connection.execute(text("DROP SCHEMA " + schema + " CASCADE"))
            external.dispose()
