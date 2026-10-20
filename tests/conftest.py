import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from erp.bootstrap import initialize
from erp.config import Settings
from erp.main import create_app
from erp.models import Department, Product, Role, User, UserRole
from erp.services import PASSWORDS
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

PASSWORD = "Fixture-" + "x" * 20


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("TEST_POSTGRES_URL") else []))
def env(tmp_path, monkeypatch, request):
    url = "sqlite:///" + str(tmp_path / "test.db")
    schema = None
    external_engine = None
    if request.param == "postgresql":
        base = os.environ["TEST_POSTGRES_URL"]
        schema = "erp_test_" + uuid4().hex
        external_engine = create_engine(base)
        with external_engine.begin() as conn:
            conn.execute(text("CREATE SCHEMA " + schema))
        url = (
            make_url(base)
            .update_query_dict({"options": "-csearch_path=" + schema})
            .render_as_string(hide_password=False)
        )
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    app = create_app(
        Settings(database_url=url, secure_cookies=False, app_origin="http://testserver")
    )
    with Session(app.state.engine, expire_on_commit=False) as db:
        admin_id = initialize(db, "admin", PASSWORD)
        db.add_all(
            [
                Department(id="dept-a", name="A"),
                Department(id="dept-b", name="B"),
                Role(id="staff", name="staff"),
                Role(id="second", name="second"),
            ]
        )
        db.flush()
        for name, dept in (("alice", "dept-a"), ("bob", "dept-b")):
            db.add(
                User(
                    id=name,
                    username=name,
                    password_hash=PASSWORDS.hash(PASSWORD),
                    department_id=dept,
                )
            )
        db.flush()
        db.add_all(
            [
                UserRole(user_id="alice", role_id="staff"),
                UserRole(user_id="alice", role_id="second"),
                UserRole(user_id="bob", role_id="staff"),
            ]
        )
        db.add_all(
            [
                Product(
                    id="product-a",
                    sku="A",
                    name="Mouse A",
                    unit="piece",
                    owner_id="alice",
                    department_id="dept-a",
                ),
                Product(
                    id="product-b",
                    sku="B",
                    name="Mouse B",
                    unit="piece",
                    owner_id="bob",
                    department_id="dept-b",
                ),
            ]
        )
        db.commit()
    clients = []

    def client(username="admin"):
        c = TestClient(app)
        assert (
            c.post(
                "/api/v1/auth/login", json={"username": username, "password": PASSWORD}
            ).status_code
            == 200
        )
        clients.append(c)
        return c

    yield {"app": app, "engine": app.state.engine, "client": client, "admin_id": admin_id}
    for c in clients:
        c.close()
    app.state.engine.dispose()
    if schema:
        with external_engine.begin() as conn:
            conn.execute(text("DROP SCHEMA " + schema + " CASCADE"))
        external_engine.dispose()


def post(client, path, payload, method="post"):
    return getattr(client, method)(
        path, json=payload, headers={"x-csrf-token": client.cookies.get("erp_csrf", "")}
    )


def grant(admin, rules):
    rev = admin.get("/api/v1/policies").json()
    return post(
        admin,
        "/api/v1/policies/publish",
        {"expected_revision": rev["number"], "rules": rev["rules"] + rules},
    )


def product_rule(**overrides):
    return {
        "id": "own-products",
        "subject": {"kind": "role", "id": "staff"},
        "resource": "products",
        "actions": ["read", "update", "create"],
        "effect": "allow",
        "scope": "own",
        "fields": {
            f: "write"
            for f in ("id", "version", "sku", "name", "unit", "owner_id", "department_id", "active")
        },
        **overrides,
    }
