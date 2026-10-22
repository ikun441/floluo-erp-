import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config
from conftest import grant, post, product_rule
from erp import shipment
from erp.audit import verify
from erp.business_models import InventoryBalance, Outbox, StockMovement
from erp.sales_models import SalesLine, SalesOrder, SalesShipment, ShipmentExecution, ShipmentLine
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_procurement import draft as purchase_draft
from test_procurement import receive
from test_procurement import setup as purchase_setup
from test_sales import action, rule
from test_sales import body as sale_body
from test_sales import draft as sale_draft


def setup(env, stock="10"):
    admin, alice, supplier, warehouse = purchase_setup(env)
    if stock is not None:
        purchase = purchase_draft(alice, supplier, quantity=stock, price="1.00")
        submitted = post(
            alice, "/api/v1/purchase_orders/" + purchase["id"] + "/submit", {"version": 1}
        )
        assert submitted.status_code == 200
        approved = post(
            admin, "/api/v1/purchase_orders/" + purchase["id"] + "/approve", {"version": 2}
        )
        assert approved.status_code == 200
        response = receive(alice, approved.json(), warehouse, quantity=stock)
        assert response.status_code == 200, response.text
    assert (
        grant(
            admin,
            [
                rule("customers"),
                rule("sales_orders"),
                rule("sales_shipments"),
                rule("warehouses", id="shipping-warehouse", scope="all", actions=["read", "ship"]),
                rule("inventory_balances", id="shipping-balances", scope="all", actions=["read"]),
                product_rule(id="shipping-products", scope="all", actions=["read"]),
            ],
        ).status_code
        == 200
    )
    customers = []
    for owner in ("alice", "bob"):
        response = post(
            admin,
            "/api/v1/customers",
            {"data": {"code": "shipping-" + owner, "name": owner, "owner_id": owner}},
        )
        assert response.status_code == 200
        customers.append(response.json()["id"])
    return admin, alice, env["client"]("bob"), customers, warehouse


def approved(admin, client, customer, quantity="6"):
    order = sale_draft(client, customer, quantity=quantity)
    submitted = action(client, order, "submit")
    assert submitted.status_code == 200
    result = action(admin, submitted.json(), "approve")
    assert result.status_code == 200
    return result.json()


def ship(client, order, warehouse, quantity="2", key="shipping-key", lines=None):
    return client.post(
        "/api/v1/sales_orders/" + order["id"] + "/ship",
        headers={"X-CSRF-Token": client.cookies["erp_csrf"], "Idempotency-Key": key},
        json={
            "version": order["version"],
            "warehouse_id": warehouse,
            "lines": lines
            if lines is not None
            else [{"line_id": order["lines"][0]["id"], "quantity": quantity}],
        },
    )


def balance(env):
    with Session(env["engine"]) as db:
        return db.scalar(
            select(InventoryBalance.quantity).where(InventoryBalance.product_id == "product-a")
        )


def test_partial_and_complete_shipments_replay_and_immutable_history(env):
    admin, alice, _, customers, warehouse = setup(env)
    row = approved(admin, alice, customers[0])
    first = ship(alice, row, warehouse)
    assert first.status_code == 200, first.text
    saved = first.json()
    assert saved["number"].startswith("SH-") and saved["lines"][0]["quantity"] == "2.0000"
    assert saved["created_at"].endswith("+00:00")
    assert "unit_price" not in json.dumps(saved) and "total" not in saved
    updated = alice.get("/api/v1/sales_orders/" + row["id"]).json()
    assert (
        updated["status"] == "partially_shipped"
        and updated["lines"][0]["shipped_quantity"] == "2.0000"
    )
    assert updated["version"] == 4 and balance(env) == Decimal(8)
    assert ship(alice, row, warehouse).json()["id"] == saved["id"]
    assert ship(alice, row, warehouse, quantity="1").status_code == 409
    assert ship(alice, row, warehouse, key="stale-version").status_code == 409
    assert action(alice, updated, "cancel").status_code == 409
    result = ship(alice, updated, warehouse, quantity="4", key="complete")
    assert result.status_code == 200, result.text
    complete = alice.get("/api/v1/sales_orders/" + row["id"]).json()
    assert complete["status"] == "shipped" and complete["lines"][0]["shipped_quantity"] == "6.0000"
    assert balance(env) == Decimal(4)
    assert ship(alice, complete, warehouse, key="after-complete").status_code == 409
    assert ship(alice, row, warehouse).json()["id"] == saved["id"]
    assert len(alice.get("/api/v1/sales_shipments?order_id=" + row["id"]).json()["items"]) == 2
    assert len(alice.get("/api/v1/stock_movements").json()["items"]) == 3
    for table in ("sales_shipment", "shipment_line", "shipment_execution", "stock_movement"):
        for mutation in (f"UPDATE {table} SET version=version+1", f"DELETE FROM {table}"):
            with Session(env["engine"]) as db, pytest.raises(DBAPIError):
                db.execute(text(mutation))
        if env["engine"].dialect.name == "postgresql":
            with Session(env["engine"]) as db, pytest.raises(DBAPIError):
                db.execute(text(f"TRUNCATE {table} CASCADE"))
    with Session(env["engine"]) as db:
        assert db.scalar(select(func.count()).select_from(ShipmentExecution)) == 2
        assert verify(db)
    with pytest.raises(RuntimeError, match="shipment history exists"):
        command.downgrade(Config("alembic.ini"), "be0f9a8b7c6d")


def test_short_stock_over_plan_missing_inventory_and_unapproved_orders(env):
    admin, alice, _, customers, warehouse = setup(env, stock="3")
    row = sale_draft(alice, customers[0], quantity="6")
    assert ship(alice, row, warehouse).status_code == 409
    row = action(admin, action(alice, row, "submit").json(), "approve").json()
    assert ship(alice, row, warehouse, quantity="4").json()["detail"] == "insufficient_stock"
    assert (
        ship(alice, row, warehouse, quantity="7").json()["detail"]
        == "invalid_or_excess_shipment_quantity"
    )
    assert balance(env) == Decimal(3)
    with Session(env["engine"]) as db:
        assert db.scalar(select(func.count()).select_from(SalesShipment)) == 0
    empty = post(
        admin,
        "/api/v1/warehouses",
        {"data": {"code": "empty", "name": "empty", "owner_id": "alice"}},
    ).json()
    assert ship(alice, row, empty["id"]).json()["detail"] == "inventory_unavailable"


def test_repeated_product_lines_are_aggregated_before_stock_change(env):
    admin, alice, _, customers, warehouse = setup(env, stock="5")
    data = sale_body(customers[0], quantity="4", price="1.00")
    data["lines"] *= 2
    response = post(alice, "/api/v1/sales_orders", data)
    assert response.status_code == 200
    row = action(admin, action(alice, response.json(), "submit").json(), "approve").json()
    request = [{"line_id": line["id"], "quantity": "3"} for line in row["lines"]]
    assert ship(alice, row, warehouse, lines=request).json()["detail"] == "insufficient_stock"
    assert balance(env) == Decimal(5)
    request[1]["quantity"] = "2"
    result = ship(alice, row, warehouse, lines=request, key="aggregate-success")
    assert result.status_code == 200, result.text
    assert balance(env) == 0 and len(result.json()["lines"]) == 2


@pytest.mark.parametrize("quantity", [1.5, True, "NaN", "0", "-1", "1.00001"])
def test_shipments_reject_invalid_quantity_and_unknown_line(env, quantity):
    admin, alice, _, customers, warehouse = setup(env)
    row = approved(admin, alice, customers[0])
    assert ship(alice, row, warehouse, quantity=quantity).status_code == 422
    assert (
        ship(alice, row, warehouse, lines=[{"line_id": "missing", "quantity": "1"}]).status_code
        == 409
    )
    duplicate = [{"line_id": row["lines"][0]["id"], "quantity": "1"}] * 2
    assert ship(alice, row, warehouse, lines=duplicate).status_code == 422
    assert ship(alice, row, warehouse, key="").status_code == 422
    assert balance(env) == 10


def test_shipments_reauthorize_replays_and_relationship_reads(env):
    admin, alice, bob, customers, warehouse = setup(env)
    row = approved(admin, alice, customers[0])
    assert ship(bob, row, warehouse).status_code == 404
    response = ship(alice, row, warehouse)
    assert response.status_code == 200
    saved = response.json()
    assert bob.get("/api/v1/sales_shipments/" + saved["id"]).status_code == 404
    assert (
        grant(
            admin, [rule("sales_shipments", id="no-shipment-read", actions=["read"], effect="deny")]
        ).status_code
        == 200
    )
    assert alice.get("/api/v1/sales_shipments?limit=1").json()["items"] == []
    movements = alice.get("/api/v1/stock_movements?limit=100").json()["items"]
    assert len(movements) == 1 and movements[0]["kind"] == "purchase_receipt"
    assert ship(alice, row, warehouse).status_code == 403
    assert balance(env) == 8


@pytest.mark.parametrize(
    "resource,field", [("inventory_balances", "quantity"), ("customers", "id"), ("products", "id")]
)
def test_hidden_reference_or_stock_quantity_cannot_be_used_for_shipping(env, resource, field):
    admin, alice, _, customers, warehouse = setup(env)
    row = approved(admin, alice, customers[0])
    policy = rule(resource, id="hidden-shipping-reference", scope="all", actions=["read"])
    policy["fields"][field] = "masked"
    assert grant(admin, [policy]).status_code == 200
    assert ship(alice, row, warehouse).status_code == 404
    assert balance(env) == 10


def test_shipment_fields_cursor_order_filter_and_safe_replay_after_deactivation(env):
    admin, alice, _, customers, warehouse = setup(env)
    row = approved(admin, alice, customers[0])
    saved = ship(alice, row, warehouse).json()
    assert (
        grant(
            admin,
            [
                rule(
                    "sales_shipments",
                    id="hide-shipment-fields",
                    actions=["read"],
                    fields={"id": "read", "number": "read", "version": "read", "lines": "hidden"},
                )
            ],
        ).status_code
        == 200
    )
    data = alice.get("/api/v1/sales_shipments/" + saved["id"]).json()
    assert "lines" not in data and "order_id" not in data
    assert alice.get("/api/v1/sales_shipments?order_id=" + row["id"]).json()["items"] == []
    assert alice.get("/api/v1/sales_shipments?after=" + saved["id"]).json()["items"] == []
    for resource, record_id in (
        ("products", "product-a"),
        ("customers", customers[0]),
        ("warehouses", warehouse),
    ):
        result = post(
            admin,
            "/api/v1/" + resource + "/" + record_id,
            {"version": 1, "data": {"active": False}},
            "patch",
        )
        assert result.status_code == 200
    config = admin.get("/api/v1/system_configuration").json()
    assert (
        post(
            admin,
            "/api/v1/system_configuration",
            {"version": config["version"], "values": {"tax_mode": "unconfigured"}},
            "patch",
        ).status_code
        == 200
    )
    assert ship(alice, row, warehouse).json()["id"] == saved["id"]
    current = alice.get("/api/v1/sales_orders/" + row["id"]).json()
    assert ship(alice, current, warehouse, key="new-disabled").status_code == 409
    assert balance(env) == 8
    assert (
        grant(
            admin, [rule("sales_shipments", id="no-create-now", actions=["create"], effect="deny")]
        ).status_code
        == 200
    )
    assert ship(alice, row, warehouse).status_code == 403


def test_shipment_requires_fields_and_final_state_permission(env):
    admin, alice, _, customers, warehouse = setup(env)
    row = approved(admin, alice, customers[0])
    deny = rule(
        "sales_orders",
        id="deny-shipped-state",
        actions=["ship"],
        effect="deny",
        conditions=[{"field": "status", "op": "eq", "value": "partially_shipped"}],
    )
    assert grant(admin, [deny]).status_code == 200
    assert ship(alice, row, warehouse).status_code == 403
    assert balance(env) == 10
    with Session(env["engine"]) as db:
        assert db.scalar(select(func.count()).select_from(SalesShipment)) == 0
        assert db.get(SalesOrder, row["id"]).version == 3
    policy = rule("sales_shipments", id="no-lines-write", actions=["create"])
    policy["fields"]["lines"] = "read"
    assert grant(admin, [policy]).status_code == 200
    assert ship(alice, row, warehouse).json()["detail"] == "field_write_denied"
    assert balance(env) == 10


def test_shipment_failure_rolls_back_all_business_records(env, monkeypatch):
    admin, alice, _, customers, warehouse = setup(env)
    row = approved(admin, alice, customers[0])

    def fail(*args):
        raise RuntimeError("private-shipping-error")

    monkeypatch.setattr(shipment, "emit", fail)
    with TestClient(env["app"], raise_server_exceptions=False) as failed:
        failed.cookies.update(alice.cookies)
        response = ship(failed, row, warehouse)
        assert response.status_code == 500 and response.json() == {"detail": "internal_error"}
    assert balance(env) == 10
    with Session(env["engine"]) as db:
        for model in (SalesShipment, ShipmentLine, ShipmentExecution):
            assert db.scalar(select(func.count()).select_from(model)) == 0
        assert db.scalar(select(func.count()).select_from(StockMovement)) == 1
        assert (
            db.scalar(
                select(func.count()).select_from(Outbox).where(Outbox.event_type == "sales.shipped")
            )
            == 0
        )
        assert db.get(SalesOrder, row["id"]).version == 3
        assert (
            db.scalar(select(SalesLine.shipped_quantity).where(SalesLine.order_id == row["id"]))
            == 0
        )
        assert verify(db)


def test_upgrade_preserves_existing_sales_and_purchase_ledger_constraints(env):
    admin, alice, _, customers, _ = setup(env)
    row = approved(admin, alice, customers[0])
    with Session(env["engine"]) as db:
        movement = db.scalar(select(StockMovement))
        old = (movement.id, movement.receipt_line_id, movement.quantity, movement.kind)
    command.downgrade(Config("alembic.ini"), "be0f9a8b7c6d")
    with env["engine"].connect() as conn:
        assert conn.scalar(text("SELECT COUNT(*) FROM sales_line")) == 1
        assert (
            conn.execute(text("SELECT id,receipt_line_id,quantity,kind FROM stock_movement")).one()[
                0
            ]
            == old[0]
        )
    command.upgrade(Config("alembic.ini"), "head")
    with Session(env["engine"]) as db:
        movement = db.get(StockMovement, old[0])
        assert (movement.id, movement.receipt_line_id, movement.quantity, movement.kind) == old
        assert (
            movement.shipment_line_id is None and db.get(SalesOrder, row["id"]).status == "approved"
        )
        assert db.scalar(select(SalesLine.shipped_quantity)) == 0
        if db.bind.dialect.name == "sqlite":
            assert db.execute(text("PRAGMA foreign_key_check")).all() == []
    checks = inspect(env["engine"]).get_check_constraints("stock_movement")
    assert any("quantity" in item["sqltext"] and ">" in item["sqltext"] for item in checks)
    for table in ("sales_line", "sales_order"):
        assert len(inspect(env["engine"]).get_check_constraints(table)) >= 3


@pytest.mark.parametrize("scenario", ["same-order", "same-key", "competing-orders"])
def test_postgres_concurrent_shipping_cannot_oversell_or_duplicate(env, scenario):
    if env["engine"].dialect.name != "postgresql":
        pytest.skip("SQLite does not provide PostgreSQL row locks")
    admin, alice, bob, customers, warehouse = setup(env)
    first = approved(admin, alice, customers[0])
    if scenario == "competing-orders":
        second = approved(admin, bob, customers[1])
        jobs = [(alice, first, "first"), (bob, second, "second")]
        quantity = "6"
    else:
        quantity = "2"
        jobs = [
            (alice, first, "shared"),
            (env["client"]("alice"), first, "shared" if scenario == "same-key" else "different"),
        ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(
                lambda job: ship(job[0], job[1], warehouse, quantity=quantity, key=job[2]), jobs
            )
        )
    codes = sorted(response.status_code for response in responses)
    assert codes == ([200, 200] if scenario == "same-key" else [200, 409]), [
        r.text for r in responses
    ]
    if scenario == "same-key":
        assert responses[0].json()["id"] == responses[1].json()["id"]
    assert balance(env) == Decimal(10) - Decimal(quantity)
    with Session(env["engine"]) as db:
        assert db.scalar(select(func.count()).select_from(SalesShipment)) == 1
        assert db.scalar(select(func.count()).select_from(ShipmentExecution)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(StockMovement)
                .where(StockMovement.kind == "sales_shipment")
            )
            == 1
        )


def test_existing_roles_do_not_gain_ship_actions_or_shipped_field(env):
    admin, alice, _, customers, warehouse = setup(env)
    row = approved(admin, alice, customers[0])
    current = admin.get("/api/v1/policies").json()
    rules = []
    for item in current["rules"]:
        if item["resource"] == "sales_shipments":
            continue
        if item["resource"] in {"sales_orders", "warehouses"}:
            item["actions"] = [action for action in item["actions"] if action != "ship"]
            item["fields"].pop("shipped_quantity", None)
        rules.append(item)
    assert (
        post(
            admin,
            "/api/v1/policies/publish",
            {"expected_revision": current["number"], "rules": rules},
        ).status_code
        == 200
    )
    visible = alice.get("/api/v1/sales_orders/" + row["id"]).json()
    assert "shipped_quantity" not in visible["lines"][0]
    assert ship(alice, row, warehouse).status_code == 404
    assert alice.get("/api/v1/sales_shipments").json()["items"] == []
    assert balance(env) == 10


def test_masked_shipment_id_hides_cursor_and_outbound_source(env):
    admin, alice, _, customers, warehouse = setup(env)
    row = approved(admin, alice, customers[0])
    saved = ship(alice, row, warehouse).json()
    policy = rule("sales_shipments", id="mask-shipment-id", actions=["read"])
    policy["fields"]["id"] = "masked"
    assert grant(admin, [policy]).status_code == 200
    assert alice.get("/api/v1/sales_shipments").json()["items"][0]["id"] == "***"
    assert alice.get("/api/v1/sales_shipments?after=0").json()["items"] == []
    assert alice.get("/api/v1/sales_shipments/" + saved["id"]).json()["id"] == "***"
    records = alice.get("/api/v1/stock_movements").json()["items"]
    assert len(records) == 1 and records[0]["kind"] == "purchase_receipt"


def test_shipment_requires_csrf_approval_and_has_no_generic_writes(env):
    admin, alice, _, customers, warehouse = setup(env)
    row = approved(admin, alice, customers[0])
    payload = {
        "version": row["version"],
        "warehouse_id": warehouse,
        "lines": [{"line_id": row["lines"][0]["id"], "quantity": "1"}],
    }
    assert (
        alice.post(
            "/api/v1/sales_orders/" + row["id"] + "/ship",
            json=payload,
            headers={"Idempotency-Key": "no-csrf"},
        ).status_code
        == 403
    )
    assert (
        post(
            alice, "/api/v1/sales_orders/" + row["id"] + "/ship", {**payload, "owner_id": "bob"}
        ).status_code
        == 422
    )
    assert post(admin, "/api/v1/sales_shipments", {"data": {}}).status_code == 404
    assert (
        grant(
            admin,
            [
                rule(
                    "sales_shipments",
                    id="needs-workflow",
                    actions=["create"],
                    requires_approval=True,
                )
            ],
        ).status_code
        == 200
    )
    assert ship(alice, row, warehouse).json()["detail"] == "approval_required"
    assert balance(env) == 10
