import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from conftest import grant, post, product_rule
from erp import sales
from erp.audit import verify
from erp.business_models import InventoryBalance, Outbox, StockMovement
from erp.business_schemas import SalesOrderInput
from erp.database import lock_gate
from erp.models import AuditEvent, User
from erp.permissions import RESOURCES, Engine, subject
from erp.sales_models import Customer, SalesLine, SalesOrder
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def rule(resource, **changes):
    return {
        "id": "sales-" + resource,
        "subject": {"kind": "role", "id": "staff"},
        "resource": resource,
        "effect": "allow",
        "scope": "own",
        "actions": sorted(RESOURCES[resource].actions),
        "fields": {key: "write" for key in RESOURCES[resource].fields},
        **changes,
    }


def configure(admin):
    settings = admin.get("/api/v1/system_configuration").json()
    response = post(
        admin,
        "/api/v1/system_configuration",
        {
            "version": settings["version"],
            "values": {
                "supported_currencies": ["CNY"],
                "tax_mode": "no_tax",
                "require_separate_approver": False,
            },
        },
        "patch",
    )
    assert response.status_code == 200, response.text


def setup(env, configured=True):
    admin, alice, bob = env["client"](), env["client"]("alice"), env["client"]("bob")
    assert (
        grant(admin, [product_rule(), rule("customers"), rule("sales_orders")]).status_code == 200
    )
    customers = []
    for owner, department in (("alice", "dept-a"), ("bob", "dept-b")):
        response = post(
            admin,
            "/api/v1/customers",
            {
                "data": {
                    "code": owner,
                    "name": owner,
                    "owner_id": owner,
                    "department_id": department,
                    "phone": "private-phone",
                }
            },
        )
        assert response.status_code == 200, response.text
        customers.append(response.json()["id"])
    if configured:
        configure(admin)
    return admin, alice, bob, customers


def body(customer, quantity="3", price="10.00", product="product-a"):
    return {
        "customer_id": customer,
        "currency": "CNY",
        "note": "sale-note",
        "lines": [{"product_id": product, "quantity": quantity, "unit_price": price}],
    }


def draft(client, customer, **kwargs):
    response = post(client, "/api/v1/sales_orders", body(customer, **kwargs))
    assert response.status_code == 200, response.text
    return response.json()


def action(client, order, operation, version=None):
    return post(
        client,
        "/api/v1/sales_orders/" + order["id"] + "/" + operation,
        {"version": version or order["version"]},
    )


def test_sales_lifecycle_safe_configuration_separate_approval_and_no_stock(env):
    admin, alice, _, customers = setup(env, configured=False)
    order = draft(alice, customers[0])
    assert order["number"].startswith("SO-") and order["total"] == "30.00"
    assert order["owner_id"] == "alice" and order["department_id"] == "dept-a"
    assert action(alice, order, "submit").status_code == 409
    configure(admin)
    before_line = order["lines"][0]["id"]
    updated = post(
        alice,
        "/api/v1/sales_orders/" + order["id"],
        {**body(customers[0], quantity="2.5", price="4.00"), "version": 1},
        "patch",
    )
    assert updated.status_code == 200, updated.text
    order = updated.json()
    assert order["version"] == 2 and order["total"] == "10.00"
    assert order["lines"][0]["id"] != before_line
    assert action(alice, order, "submit", version=1).status_code == 409
    order = action(alice, order, "submit").json()
    assert order["status"] == "submitted"
    assert action(alice, order, "approve").status_code == 403
    assert (
        post(
            alice,
            "/api/v1/sales_orders/" + order["id"],
            {**body(customers[0]), "version": order["version"]},
            "patch",
        ).status_code
        == 409
    )
    result = action(admin, order, "approve")
    assert result.status_code == 200, result.text
    order = result.json()
    assert order["status"] == "approved" and order["approved_by"] == env["admin_id"]
    assert action(admin, order, "approve").status_code == 409
    cancelled = action(alice, order, "cancel")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert action(alice, cancelled.json(), "cancel").status_code == 409
    with Session(env["engine"]) as db:
        assert db.scalar(select(func.count()).select_from(SalesOrder)) == 1
        assert db.scalar(select(func.count()).select_from(SalesLine)) == 1
        assert db.scalar(select(func.count()).select_from(InventoryBalance)) == 0
        assert db.scalar(select(func.count()).select_from(StockMovement)) == 0
        assert (
            db.scalar(
                select(func.count()).select_from(Outbox).where(Outbox.event_type.like("sales.%"))
            )
            == 5
        )
        assert verify(db)
        events = list(db.scalars(select(AuditEvent).where(AuditEvent.event.like("%sales_orders%"))))
        assert any(event.result == 403 for event in events)
        assert "sale-note" not in json.dumps([event.details for event in events])


def test_sales_scopes_spoofing_references_and_csrf(env):
    admin, alice, bob, customers = setup(env)
    a = draft(alice, customers[0])
    b = draft(bob, customers[1], product="product-b")
    assert alice.get("/api/v1/sales_orders?limit=1").json()["items"][0]["id"] == a["id"]
    assert alice.get("/api/v1/sales_orders/" + b["id"]).status_code == 404
    assert (
        post(
            alice, "/api/v1/sales_orders/" + b["id"], {**body(customers[0]), "version": 1}, "patch"
        ).status_code
        == 404
    )
    for key, value in (
        ("owner_id", "bob"),
        ("department_id", "dept-b"),
        ("total", "0.00"),
        ("status", "approved"),
    ):
        assert (
            post(alice, "/api/v1/sales_orders", {**body(customers[0]), key: value}).status_code
            == 422
        )
    for customer in (customers[1], "missing"):
        assert post(alice, "/api/v1/sales_orders", body(customer)).status_code == 404
    assert alice.post("/api/v1/sales_orders", json=body(customers[0])).status_code == 403
    assert (
        post(alice, "/api/v1/sales_orders/" + a["id"] + "/receive", {"version": 1}).status_code
        == 404
    )
    assert alice.get("/api/v1/sales_orders?status=invalid").status_code == 422
    assert alice.get("/api/v1/sales_orders?limit=101").status_code == 422
    assert alice.get("/api/v1/sales_orders?after=" + a["id"]).json()["items"] == []


def test_sales_amount_plan_boundaries_do_not_write(env):
    _, alice, _, customers = setup(env)
    cases = json.loads((Path(__file__).parent / "fixtures/sales_amount_cases.json").read_text())
    with Session(env["engine"]) as db:
        lock_gate(db)
        engine = Engine(db, subject(db, db.get(User, "alice")))
        for case in cases:
            data = SalesOrderInput.model_validate(
                body(customers[0], case["quantity"], case["unit_price"])
            )
            if case["expected_amount"] is None:
                with pytest.raises(HTTPException) as error:
                    sales.prepare_draft(db, engine, data)
                assert error.value.status_code == 422
            else:
                _, values, lines = sales.prepare_draft(db, engine, data)
                assert values["total"] == Decimal(case["expected_amount"]), case["name"]
                assert lines[0].amount == values["total"]
        assert db.scalar(select(func.count()).select_from(SalesOrder)) == 0
    overflow = body(customers[0], "1", "9999999999999999.99")
    overflow["lines"] *= 2
    assert post(alice, "/api/v1/sales_orders", overflow).status_code == 422


@pytest.mark.parametrize("value", [1.5, True, "NaN", "Infinity", "-1", "0", "1.12345"])
def test_sales_rejects_invalid_quantities(env, value):
    _, alice, _, customers = setup(env)
    assert (
        post(alice, "/api/v1/sales_orders", body(customers[0], quantity=value)).status_code == 422
    )


@pytest.mark.parametrize("resource,field", [("customers", "id"), ("products", "id")])
def test_sales_relationship_projection_filters_before_paging(env, resource, field):
    admin, alice, _, customers = setup(env)
    row = draft(alice, customers[0])
    policy = rule(resource, id="hide-reference", actions=["read"])
    policy["fields"][field] = "masked"
    assert grant(admin, [policy]).status_code == 200
    assert alice.get("/api/v1/sales_orders?limit=1").json()["items"] == []
    assert alice.get("/api/v1/sales_orders/" + row["id"]).status_code == 404
    assert action(alice, row, "submit").status_code == 404


def test_sales_money_projection_status_filter_and_current_policy(env):
    admin, alice, _, customers = setup(env)
    row = draft(alice, customers[0])
    policy = rule("sales_orders", id="mask-price", actions=["read"])
    policy["fields"]["unit_price"] = "masked"
    assert grant(admin, [policy]).status_code == 200
    data = alice.get("/api/v1/sales_orders/" + row["id"]).json()
    assert data["total"] == data["lines"][0]["amount"] == data["lines"][0]["unit_price"] == "***"
    policy = rule("sales_orders", id="hide-amount-state", actions=["read"])
    policy["fields"].update(line_amount="hidden", status="hidden")
    assert grant(admin, [policy]).status_code == 200
    data = alice.get("/api/v1/sales_orders/" + row["id"]).json()
    assert (
        "total" not in data
        and "unit_price" not in data["lines"][0]
        and "amount" not in data["lines"][0]
    )
    assert alice.get("/api/v1/sales_orders?status=draft").json()["items"] == []
    assert grant(admin, [rule("sales_orders", id="deny-all", effect="deny")]).status_code == 200
    assert alice.get("/api/v1/sales_orders").json()["items"] == []
    assert action(alice, row, "submit").status_code == 404


def test_sales_checks_candidate_amount_fields_and_pending_approval(env):
    admin, alice, _, customers = setup(env)
    row = draft(alice, customers[0])
    deny = rule(
        "sales_orders",
        id="deny-expensive",
        effect="deny",
        actions=["update"],
        conditions=[{"field": "total", "op": "gt", "value": "50.00"}],
    )
    assert grant(admin, [deny]).status_code == 200
    response = post(
        alice,
        "/api/v1/sales_orders/" + row["id"],
        {**body(customers[0], quantity="10"), "version": 1},
        "patch",
    )
    assert response.status_code == 403
    assert alice.get("/api/v1/sales_orders/" + row["id"]).json()["total"] == "30.00"
    restricted = rule("sales_orders", id="readonly-price", actions=["update"])
    restricted["fields"]["unit_price"] = "read"
    assert (
        grant(
            admin,
            [
                restricted,
                rule(
                    "sales_orders",
                    id="approval-required",
                    actions=["submit"],
                    requires_approval=True,
                ),
            ],
        ).status_code
        == 200
    )
    assert (
        post(
            alice,
            "/api/v1/sales_orders/" + row["id"],
            {**body(customers[0]), "version": 1},
            "patch",
        ).status_code
        == 403
    )
    assert action(alice, row, "submit").json()["detail"] == "approval_required"
    assert alice.get("/api/v1/sales_orders/" + row["id"]).json()["version"] == 1


def test_sales_transaction_rollback_and_existing_role_default_deny(env, monkeypatch):
    admin, alice, _, customers = setup(env)

    def fail(*args):
        raise RuntimeError("private-error")

    monkeypatch.setattr(sales, "emit", fail)
    with TestClient(env["app"], raise_server_exceptions=False) as failed:
        failed.cookies.update(alice.cookies)
        response = post(failed, "/api/v1/sales_orders", body(customers[0]))
        assert response.status_code == 500 and response.json() == {"detail": "internal_error"}
    with Session(env["engine"]) as db:
        assert db.scalar(select(func.count()).select_from(SalesOrder)) == 0
        assert db.scalar(select(func.count()).select_from(SalesLine)) == 0
        assert db.scalar(select(func.count()).select_from(Outbox)) == 0
        assert verify(db)
    current = admin.get("/api/v1/policies").json()
    old_rules = [
        item for item in current["rules"] if item["resource"] not in {"customers", "sales_orders"}
    ]
    assert (
        post(
            admin,
            "/api/v1/policies/publish",
            {"expected_revision": current["number"], "rules": old_rules},
        ).status_code
        == 200
    )
    assert admin.get("/api/v1/sales_orders").json()["items"] == []
    assert admin.get("/api/v1/customers").json()["items"] == []
    assert post(admin, "/api/v1/sales_orders", body(customers[0])).status_code == 404


def test_sales_migration_refuses_customer_history_loss(env):
    setup(env)
    with pytest.raises(RuntimeError, match="sales/customer data exists"):
        command.downgrade(Config("alembic.ini"), "ad9e8f7a6b5c")
    with Session(env["engine"]) as db:
        assert db.scalar(select(func.count()).select_from(Customer)) == 2


def test_concurrent_sales_edit_uses_postgres_row_locks(env):
    if env["engine"].dialect.name != "postgresql":
        pytest.skip("SQLite does not provide PostgreSQL row locks")
    _, alice, _, customers = setup(env)
    row = draft(alice, customers[0])
    other = env["client"]("alice")

    def update(client, amount):
        return post(
            client,
            "/api/v1/sales_orders/" + row["id"],
            {**body(customers[0], quantity=amount), "version": 1},
            "patch",
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(lambda pair: update(*pair), [(alice, "2"), (other, "5")]))
    assert sorted(codes) == [200, 409]
    data = alice.get("/api/v1/sales_orders/" + row["id"]).json()
    assert data["version"] == 2 and len(data["lines"]) == 1


@pytest.mark.parametrize("target", ["customers", "products"])
def test_sales_inactive_references_block_creation_and_submission_but_allow_cancellation(
    env, target
):
    admin, alice, _, customers = setup(env)
    row = draft(alice, customers[0])
    record_id = customers[0] if target == "customers" else "product-a"
    response = post(
        admin,
        "/api/v1/" + target + "/" + record_id,
        {"version": 1, "data": {"active": False}},
        "patch",
    )
    assert response.status_code == 200
    assert post(alice, "/api/v1/sales_orders", body(customers[0])).status_code == 409
    assert action(alice, row, "submit").status_code == 409
    assert action(alice, row, "cancel").status_code == 200


def test_sales_transition_rechecks_target_state_policy(env):
    admin, alice, _, customers = setup(env)
    row = draft(alice, customers[0])
    deny = rule(
        "sales_orders",
        id="deny-submitted",
        effect="deny",
        actions=["submit"],
        conditions=[{"field": "status", "op": "eq", "value": "submitted"}],
    )
    assert grant(admin, [deny]).status_code == 200
    assert action(alice, row, "submit").status_code == 403
    assert alice.get("/api/v1/sales_orders/" + row["id"]).json()["status"] == "draft"


def test_sales_department_reader_and_write_only_acknowledgement(env):
    admin, alice, bob, customers = setup(env)
    row = draft(alice, customers[0])
    # Bob can view department A only via an explicit designated-departments policy.
    assert (
        grant(
            admin,
            [
                rule(
                    "sales_orders",
                    id="department-a-reader",
                    subject={"kind": "user", "id": "bob"},
                    scope="departments",
                    scope_ids=["dept-a"],
                    actions=["read"],
                ),
                rule("customers", id="all-customers-reader", actions=["read"], scope="all"),
                product_rule(id="all-products-reader", scope="all", actions=["read"]),
            ],
        ).status_code
        == 200
    )
    assert bob.get("/api/v1/sales_orders/" + row["id"]).status_code == 200
    assert action(bob, row, "cancel").status_code == 404
    assert (
        grant(
            admin, [rule("sales_orders", id="deny-sales-read", effect="deny", actions=["read"])]
        ).status_code
        == 200
    )
    response = post(alice, "/api/v1/sales_orders", body(customers[0]))
    assert response.status_code == 200 and response.json() == {"saved": True}


def test_concurrent_sales_approval_creates_one_transition(env):
    if env["engine"].dialect.name != "postgresql":
        pytest.skip("SQLite does not provide PostgreSQL row locks")
    admin, alice, _, customers = setup(env)
    row = action(alice, draft(alice, customers[0]), "submit").json()
    second = env["client"]()
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda client: action(client, row, "approve"), [admin, second]))
    assert sorted(response.status_code for response in responses) == [200, 409]
    with Session(env["engine"]) as db:
        assert (
            db.scalar(
                select(func.count()).select_from(Outbox).where(Outbox.event_type == "sales.approve")
            )
            == 1
        )
        assert db.get(SalesOrder, row["id"]).version == 3
