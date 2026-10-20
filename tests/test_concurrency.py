from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from conftest import grant, post, product_rule
from erp.database import lock_gate
from erp.models import PolicyRevision
from sqlalchemy.orm import Session


def test_postgres_concurrent_version_conflict(env):
    if env["engine"].dialect.name != "postgresql":
        pytest.skip("requires real PostgreSQL row locking")
    a, b = env["client"](), env["client"]()

    def change(client, name):
        return post(
            client, "/api/v1/products/product-a", {"version": 1, "data": {"name": name}}, "patch"
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(change, a, "one")
        second = pool.submit(change, b, "two")
        assert sorted([first.result(timeout=15), second.result(timeout=15)]) == [200, 409]


def test_postgres_revocation_serializes_before_waiting_write(env):
    if env["engine"].dialect.name != "postgresql":
        pytest.skip("requires real PostgreSQL row locking")
    admin, alice = env["client"](), env["client"]("alice")
    assert grant(admin, [product_rule()]).status_code == 200
    started = Event()

    def change():
        started.set()
        return post(
            alice,
            "/api/v1/products/product-a",
            {"version": 1, "data": {"name": "must not commit"}},
            "patch",
        ).status_code

    with ThreadPoolExecutor(max_workers=1) as pool:
        with Session(env["engine"]) as db:
            gate = lock_gate(db)
            previous = db.get(PolicyRevision, gate.revision_id)
            revision = PolicyRevision(
                number=previous.number + 1,
                author_id=env["admin_id"],
                rules=[r for r in previous.rules if r["id"] != "own-products"],
            )
            db.add(revision)
            db.flush()
            gate.revision_id = revision.id
            waiting = pool.submit(change)
            assert started.wait(timeout=5)
            db.commit()
        assert waiting.result(timeout=15) == 404
    assert admin.get("/api/v1/products/product-a").json()["name"] == "Mouse A"
