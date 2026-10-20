from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from conftest import grant, post, product_rule
from erp import procurement
from erp.audit import verify
from erp.business_models import (
    CommandExecution,
    InventoryBalance,
    Outbox,
    PurchaseLine,
    PurchaseOrder,
    PurchaseReceipt,
    ReceiptLine,
    StockMovement,
)
from erp.models import AuditEvent
from erp.permissions import RESOURCES
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session


def rule(resource, **changes):
    return {
        "id": "buyer-" + resource,
        "subject": {"kind": "user", "id": "alice"},
        "resource": resource,
        "effect": "allow",
        "scope": "own" if RESOURCES[resource].owner_column else "all",
        "actions": sorted(RESOURCES[resource].actions),
        "fields": {f: "write" for f in RESOURCES[resource].fields},
        **changes,
    }


def setup(env, configure=True):
    admin, buyer = env["client"](), env["client"]("alice")
    rules = [
        product_rule(),
        rule("purchase_orders"),
        rule("purchase_receipts"),
        rule("suppliers", actions=["read"], scope="all"),
        rule("warehouses", actions=["read", "receive"], scope="all"),
        rule("inventory_balances", scope="all"),
        rule("stock_movements", scope="all"),
    ]
    assert grant(admin, rules).status_code == 200
    supplier = post(
        admin,
        "/api/v1/suppliers",
        {"data": {"code": "supplier", "name": "supplier", "owner_id": "alice"}},
    ).json()
    warehouse = post(
        admin,
        "/api/v1/warehouses",
        {
            "data": {
                "code": "warehouse",
                "name": "warehouse",
                "owner_id": "alice",
                "department_id": "dept-a",
            }
        },
    ).json()
    if configure:
        settings = admin.get("/api/v1/system_configuration").json()
        result = post(
            admin,
            "/api/v1/system_configuration",
            {
                "version": settings["version"],
                "values": {"supported_currencies": ["CNY"], "tax_mode": "no_tax"},
            },
            "patch",
        )
        assert result.status_code == 200, result.text
        assert result.json()["require_separate_approver"] is True
    return admin, buyer, supplier["id"], warehouse["id"]


def draft(buyer, supplier, quantity="3", price="10.00"):
    response = post(
        buyer,
        "/api/v1/purchase_orders",
        {
            "supplier_id": supplier,
            "currency": "CNY",
            "lines": [{"product_id": "product-a", "quantity": quantity, "unit_price": price}],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def approved(env):
    admin, buyer, supplier, warehouse = setup(env)
    row = draft(buyer, supplier)
    result = post(buyer, "/api/v1/purchase_orders/" + row["id"] + "/submit", {"version": 1})
    assert result.status_code == 200, result.text
    result = post(admin, "/api/v1/purchase_orders/" + row["id"] + "/approve", {"version": 2})
    assert result.status_code == 200, result.text
    return admin, buyer, warehouse, result.json()


def receive(buyer, row, warehouse, quantity="3", key="receipt-key"):
    return buyer.post(
        "/api/v1/purchase_orders/" + row["id"] + "/receive",
        json={
            "version": row["version"],
            "warehouse_id": warehouse,
            "lines": [{"line_id": row["lines"][0]["id"], "quantity": quantity}],
        },
        headers={"x-csrf-token": buyer.cookies["erp_csrf"], "Idempotency-Key": key},
    )


def test_safe_configuration_money_precision_and_no_identity_spoofing(env):
    admin, buyer, supplier, _ = setup(env, configure=False)
    row = draft(buyer, supplier)
    assert row["owner_id"] == "alice" and row["department_id"] == "dept-a"
    assert row["total"] == "30.00" and row["lines"][0]["unit_price"] == "10.00"
    assert (
        post(buyer, f"/api/v1/purchase_orders/{row['id']}/submit", {"version": 1}).status_code
        == 409
    )
    for qty, price, expected in [
        (1.5, "1", 422),
        ("0.0001", "0.01", 422),
        ("99999999999999.9999", "9999999999999999.99", 422),
    ]:
        response = post(
            buyer,
            "/api/v1/purchase_orders",
            {
                "supplier_id": supplier,
                "currency": "CNY",
                "lines": [{"product_id": "product-a", "quantity": qty, "unit_price": price}],
            },
        )
        assert response.status_code == expected, response.text
    assert (
        post(
            buyer,
            "/api/v1/purchase_orders",
            {
                "supplier_id": supplier,
                "currency": "CNY",
                "owner_id": "bob",
                "lines": [{"product_id": "product-a", "quantity": 1, "unit_price": "1"}],
            },
        ).status_code
        == 422
    )
    assert (
        post(buyer, f"/api/v1/purchase_orders/{row['id']}/approve", {"version": 1}).status_code
        == 409
    )
    assert admin.get("/api/v1/system_configuration").json()["tax_mode"] == "unconfigured"


def test_closed_loop_partial_receipt_inventory_ledger_and_immutable_records(env):
    admin, buyer, warehouse, row = approved(env)
    first = receive(buyer, row, warehouse, "1", "first")
    assert first.status_code == 200, first.text
    row = buyer.get("/api/v1/purchase_orders/" + row["id"]).json()
    assert row["status"] == "partially_received" and row["version"] == 4
    assert receive(buyer, row, warehouse, "3", "excess").status_code == 409
    assert (
        post(buyer, f"/api/v1/purchase_orders/{row['id']}/cancel", {"version": 4}).status_code
        == 409
    )
    second = receive(buyer, row, warehouse, "2", "second")
    assert second.status_code == 200, second.text
    final = buyer.get("/api/v1/purchase_orders/" + row["id"]).json()
    assert final["status"] == "received" and final["version"] == 5
    assert buyer.get("/api/v1/inventory_balances").json()["items"][0]["quantity"] == "3.0000"
    assert len(buyer.get("/api/v1/stock_movements").json()["items"]) == 2
    with Session(env["engine"]) as db:
        assert db.scalar(select(func.sum(StockMovement.quantity))) == Decimal(3)
        assert db.scalar(select(InventoryBalance.quantity)) == Decimal(3)
        assert db.scalar(select(func.count()).select_from(Outbox)) == 5
        assert verify(db)
        for table in ("purchase_receipt", "receipt_line", "stock_movement", "command_execution"):
            with pytest.raises(DBAPIError):
                db.execute(text(f"DELETE FROM {table}"))
            db.rollback()
    assert admin.get("/api/v1/purchase_receipts").status_code == 200


def test_self_approval_cross_user_and_unreadable_product_are_blocked(env):
    admin, buyer, supplier, _ = setup(env)
    row = draft(buyer, supplier)
    assert (
        post(buyer, f"/api/v1/purchase_orders/{row['id']}/submit", {"version": 1}).status_code
        == 200
    )
    assert (
        post(buyer, f"/api/v1/purchase_orders/{row['id']}/approve", {"version": 2}).status_code
        == 403
    )
    bob = env["client"]("bob")
    assert bob.get("/api/v1/purchase_orders/" + row["id"]).status_code == 404
    assert (
        post(
            bob,
            "/api/v1/purchase_orders/" + row["id"],
            {
                "version": 2,
                "supplier_id": supplier,
                "currency": "CNY",
                "lines": [{"product_id": "product-a", "quantity": 1, "unit_price": 1}],
            },
            "patch",
        ).status_code
        == 404
    )
    assert (
        post(
            buyer,
            "/api/v1/purchase_orders",
            {
                "supplier_id": supplier,
                "currency": "CNY",
                "lines": [{"product_id": "product-b", "quantity": 1, "unit_price": 1}],
            },
        ).status_code
        == 404
    )


def test_idempotent_replay_payload_conflict_and_revocation(env):
    admin, buyer, warehouse, row = approved(env)
    one = receive(buyer, row, warehouse)
    two = receive(buyer, row, warehouse)
    assert one.status_code == two.status_code == 200, (one.text, two.text)
    assert one.json()["id"] == two.json()["id"]
    mask = rule(
        "purchase_receipts",
        id="receipt-current-projection",
        actions=["read"],
        fields={"id": "read", "version": "read", "number": "masked"},
    )
    assert grant(admin, [mask]).status_code == 200
    replay = receive(buyer, row, warehouse)
    assert (
        replay.status_code == 200
        and replay.json()["number"] == "***"
        and "lines" not in replay.json()
    )
    assert receive(buyer, row, warehouse, "2").status_code == 409
    revision = admin.get("/api/v1/policies").json()
    assert (
        post(
            admin,
            "/api/v1/policies/publish",
            {
                "expected_revision": revision["number"],
                "rules": [r for r in revision["rules"] if r["id"] != "buyer-purchase_receipts"],
            },
        ).status_code
        == 200
    )
    assert receive(buyer, row, warehouse).status_code == 403
    with Session(env["engine"]) as db:
        assert db.scalar(select(func.count()).select_from(StockMovement)) == 1
        assert db.scalar(select(InventoryBalance.quantity)) == Decimal(3)


def test_mid_receipt_failure_rolls_back_every_business_write(env, monkeypatch):
    _, buyer, warehouse, row = approved(env)
    original = procurement.emit

    def fail(db, order, kind):
        if kind == "purchase.received":
            raise HTTPException(409, "injected_storage_failure")
        return original(db, order, kind)

    monkeypatch.setattr(procurement, "emit", fail)
    assert receive(buyer, row, warehouse).status_code == 409
    with Session(env["engine"]) as db:
        for model in (
            PurchaseReceipt,
            ReceiptLine,
            StockMovement,
            InventoryBalance,
            CommandExecution,
        ):
            assert db.scalar(select(func.count()).select_from(model)) == 0
        assert db.get(PurchaseOrder, row["id"]).status == "approved"
        assert db.scalar(select(PurchaseLine.received_quantity)) == 0
        assert db.scalar(select(AuditEvent.result).order_by(AuditEvent.seq.desc()).limit(1)) == 409
        assert verify(db)


def test_amount_condition_and_all_cost_projections(env):
    admin, buyer, supplier, _ = setup(env)
    denied = rule(
        "purchase_orders",
        id="deny-large",
        effect="deny",
        actions=["create"],
        conditions=[{"field": "total", "op": "gt", "value": "100.00"}],
    )
    assert grant(admin, [denied]).status_code == 200
    assert (
        post(
            buyer,
            "/api/v1/purchase_orders",
            {
                "supplier_id": supplier,
                "currency": "CNY",
                "lines": [{"product_id": "product-a", "quantity": 20, "unit_price": "10.00"}],
            },
        ).status_code
        == 403
    )
    row = draft(buyer, supplier)
    mask = rule("purchase_orders", id="mask-price", actions=["read"])
    mask["fields"]["unit_price"] = "masked"
    assert grant(admin, [mask]).status_code == 200
    visible = buyer.get("/api/v1/purchase_orders/" + row["id"]).json()
    assert (
        visible["total"]
        == visible["lines"][0]["unit_price"]
        == visible["lines"][0]["amount"]
        == "***"
    )
    revision = admin.get("/api/v1/policies").json()
    assert (
        post(
            admin,
            "/api/v1/policies/publish",
            {
                "expected_revision": revision["number"],
                "rules": [r for r in revision["rules"] if r["id"] != "own-products"],
            },
        ).status_code
        == 200
    )
    assert buyer.get("/api/v1/purchase_orders?limit=1").json()["items"] == []
    assert buyer.get("/api/v1/purchase_orders/" + row["id"]).status_code == 404


@pytest.mark.parametrize("same_key", [False, True])
def test_postgres_concurrent_receipts(env, same_key):
    if env["engine"].dialect.name != "postgresql":
        pytest.skip("requires real PostgreSQL locking")
    _, buyer, warehouse, row = approved(env)
    other = env["client"]("alice")
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(receive, buyer, row, warehouse, "3", "same")
        b = pool.submit(receive, other, row, warehouse, "3", "same" if same_key else "different")
        results = [a.result(timeout=15), b.result(timeout=15)]
    assert sorted(r.status_code for r in results) == ([200, 200] if same_key else [200, 409]), [
        r.text for r in results
    ]
    if same_key:
        assert results[0].json()["id"] == results[1].json()["id"]
    with Session(env["engine"]) as db:
        assert db.scalar(select(InventoryBalance.quantity)) == Decimal(3)
        assert db.scalar(select(func.count()).select_from(StockMovement)) == 1


def test_configuration_partial_write_preserves_protected_values(env):
    admin, buyer, _, _ = setup(env)
    settings_rule = rule("system_configuration", actions=["read", "update"])
    settings_rule["fields"] = {
        "id": "read",
        "version": "read",
        "supported_currencies": "write",
        "tax_mode": "read",
        "require_separate_approver": "read",
    }
    assert grant(admin, [settings_rule]).status_code == 200
    before = buyer.get("/api/v1/system_configuration").json()
    response = post(
        buyer,
        "/api/v1/system_configuration",
        {"version": before["version"], "values": {"supported_currencies": ["CNY", "USD"]}},
        "patch",
    )
    assert response.status_code == 200, response.text
    assert (
        response.json()["tax_mode"] == "no_tax"
        and response.json()["require_separate_approver"] is True
    )
    assert (
        post(
            buyer,
            "/api/v1/system_configuration",
            {"version": response.json()["version"], "values": {"require_separate_approver": False}},
            "patch",
        ).status_code
        == 403
    )


@pytest.mark.parametrize("resource", ["products", "purchase_orders"])
def test_hidden_id_cannot_be_probed_using_pagination_cursor(env, resource):
    admin, buyer, supplier, _ = setup(env)
    draft(buyer, supplier)
    policy = rule(resource, id="hide-record-id", actions=["read"])
    policy["fields"]["id"] = "hidden"
    assert grant(admin, [policy]).status_code == 200
    assert "id" not in buyer.get("/api/v1/" + resource).json()["items"][0]
    for cursor in ("0", "f", "00000000-0000-0000-0000-000000000000"):
        assert buyer.get("/api/v1/" + resource + "?after=" + cursor).json()["items"] == []


def test_unexpected_failure_is_audited_after_inventory_rollback(env, monkeypatch):
    from fastapi.testclient import TestClient

    _, buyer, warehouse, row = approved(env)

    def failure(*args):
        raise RuntimeError("simulated non-domain failure")

    monkeypatch.setattr(procurement, "emit", failure)
    with TestClient(env["app"], raise_server_exceptions=False) as client:
        client.cookies.update(buyer.cookies)
        response = receive(client, row, warehouse)
        assert response.status_code == 500
        assert response.json() == {"detail": "internal_error"}
        assert response.headers["x-trace-id"] and response.headers["cache-control"] == "no-store"
    with Session(env["engine"]) as db:
        assert db.scalar(select(func.count()).select_from(StockMovement)) == 0
        assert db.scalar(select(func.count()).select_from(PurchaseReceipt)) == 0
        assert db.scalar(select(AuditEvent.result).order_by(AuditEvent.seq.desc()).limit(1)) == 500
        assert verify(db)


def test_disabled_business_rules_block_new_receipt_without_stock_changes(env):
    admin, buyer, warehouse, row = approved(env)
    configuration = admin.get("/api/v1/system_configuration").json()
    assert (
        post(
            admin,
            "/api/v1/system_configuration",
            {"version": configuration["version"], "values": {"tax_mode": "unconfigured"}},
            "patch",
        ).status_code
        == 200
    )
    assert receive(buyer, row, warehouse).status_code == 409
    with Session(env["engine"]) as db:
        assert db.scalar(select(func.count()).select_from(StockMovement)) == 0
        assert db.get(PurchaseOrder, row["id"]).status == "approved"
