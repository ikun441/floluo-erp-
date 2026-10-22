import csv
import io
import json

import pytest
from conftest import grant, post
from erp import reports
from erp.audit import verify
from erp.models import AuditEvent
from erp.permissions import RESOURCES
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_sales import draft as sale_draft
from test_sales import rule
from test_shipments import approved, setup, ship


def report(client, name="inventory", suffix=""):
    return client.get("/api/v1/reports/" + name + suffix)


def change(admin, resource, **changes):
    return grant(
        admin,
        [
            rule(
                resource,
                id="report-extra-" + str(len(admin.get("/api/v1/policies").json()["rules"])),
                **changes,
            )
        ],
    )


def test_real_balances_movements_and_orders_with_current_authorization(env):
    admin, alice, _, customers, warehouse = setup(env)
    order = approved(admin, alice, customers[0])
    assert ship(alice, order, warehouse, quantity="2").status_code == 200
    # New read/report/export grants must be explicit for an upgraded role.
    assert change(admin, "inventory_balances", scope="all").status_code == 200
    assert change(admin, "stock_movements", scope="all").status_code == 200
    result = report(alice).json()
    assert result["source_rows"] == 1
    assert result["items"][0]["quantity"] == "8.0000"
    assert result["items"][0]["product_id"] == "product-a"
    movements = report(alice, "movements").json()
    assert {r["kind"]: r["quantity"] for r in movements["items"]} == {
        "purchase_receipt": "10.0000",
        "sales_shipment": "2.0000",
    }
    sales = report(alice, "sales", "?metric=amount").json()
    assert sales["source_rows"] == 1 and sales["items"][0]["status"] == "partially_shipped"
    assert sales["items"][0]["amount"] == "60.00"
    purchases = report(alice, "purchases", "?metric=amount").json()
    assert purchases["items"][0]["amount"] == "10.00"
    exported = report(alice, "inventory", "/export")
    assert exported.status_code == 200 and "text/csv" in exported.headers["content-type"]
    assert exported.headers["cache-control"] == "no-store"
    rows = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
    assert rows[0]["quantity"] == "8.0000"
    with Session(env["engine"]) as db:
        event = db.scalars(
            select(AuditEvent)
            .where(AuditEvent.event == "GET /api/v1/reports/{name}/export")
            .order_by(AuditEvent.seq.desc())
        ).first()
        assert event.details["export"] is True and event.details["source_rows"] == 1
        assert "8.0000" not in json.dumps(event.details)
        assert verify(db)


def test_old_roles_and_export_do_not_inherit_new_permissions(env):
    admin, alice, _, _, _ = setup(env)
    rev = admin.get("/api/v1/policies").json()
    for item in rev["rules"]:
        if item["resource"] == "inventory_balances" and item["subject"].get("id") in {
            "alice",
            "staff",
        }:
            item["actions"] = ["read"]
    assert (
        post(
            admin,
            "/api/v1/policies/publish",
            {"expected_revision": rev["number"], "rules": rev["rules"]},
        ).status_code
        == 200
    )
    assert report(alice).status_code == 403
    assert report(env["client"]("bob"), "inventory").status_code == 403
    assert change(admin, "inventory_balances", scope="all", actions=["report"]).status_code == 200
    assert report(alice).status_code == 200
    assert report(alice, suffix="/export").status_code == 403
    unauthenticated = __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(
        env["app"]
    )
    assert report(unauthenticated).status_code == 401
    unauthenticated.close()


@pytest.mark.parametrize("action", ["read", "report", "export"])
@pytest.mark.parametrize("mode", ["masked", "hidden"])
def test_each_action_field_restriction_excludes_values_before_filtering(env, action, mode):
    admin, alice, _, _, warehouse = setup(env)
    assert change(admin, "inventory_balances", scope="all").status_code == 200
    fields = {f: "read" for f in RESOURCES["inventory_balances"].fields}
    fields["quantity"] = mode
    assert (
        change(
            admin, "inventory_balances", scope="all", actions=[action], fields=fields
        ).status_code
        == 200
    )
    response = report(
        alice, suffix="/export" if action == "export" else "?warehouse_id=" + warehouse
    )
    assert response.status_code == 200
    if action == "export":
        assert len(response.content.decode("utf-8-sig").splitlines()) == 1
        assert report(alice).json()["source_rows"] == 1
    else:
        assert response.json()["items"] == [] and response.json()["source_rows"] == 0


@pytest.mark.parametrize("action", ["read", "report", "export"])
@pytest.mark.parametrize("restriction", ["deny", "approval"])
def test_explicit_denials_and_pending_actions_never_contribute(env, action, restriction):
    admin, alice, _, _, _ = setup(env)
    assert change(admin, "inventory_balances", scope="all").status_code == 200
    changes = {"effect": "deny"} if restriction == "deny" else {"requires_approval": True}
    assert (
        change(admin, "inventory_balances", scope="all", actions=[action], **changes).status_code
        == 200
    )
    response = report(alice, suffix="/export" if action == "export" else "")
    assert response.status_code == 200
    if action == "export":
        assert len(response.content.decode("utf-8-sig").splitlines()) == 1
    else:
        assert response.json()["items"] == []


def test_related_field_and_source_scope_do_not_leak_via_groups(env):
    admin, alice, _, _, warehouse = setup(env)
    assert change(admin, "inventory_balances", scope="all").status_code == 200
    fields = {f: "read" for f in RESOURCES["products"].fields}
    fields["name"] = "masked"
    assert (
        change(admin, "products", scope="all", actions=["read"], fields=fields).status_code == 200
    )
    assert report(alice, suffix="?warehouse_id=" + warehouse).json()["items"] == []
    # Existing read projection's masked name cannot be recovered through a dimension.
    assert "Mouse A" not in report(alice).text


def test_movements_reuse_source_order_visibility(env):
    admin, alice, _, _, _ = setup(env)
    assert report(alice, "movements").json()["source_rows"] == 1
    assert (
        change(admin, "purchase_orders", scope="all", actions=["read"], effect="deny").status_code
        == 200
    )
    assert report(alice, "movements").json()["items"] == []
    assert report(alice, "movements", "/export").content.decode("utf-8-sig").count("\n") == 1


def test_counts_can_be_read_without_financial_fields_and_currencies_remain_separate(env):
    admin, alice, _, customers, _ = setup(env)
    sale_draft(alice, customers[0], quantity="1")
    # Drafts permit an explicit currency; no implicit conversion is performed.
    response = post(
        alice,
        "/api/v1/sales_orders",
        {
            "customer_id": customers[0],
            "currency": "USD",
            "note": "",
            "lines": [{"product_id": "product-a", "quantity": "2", "unit_price": "7.00"}],
        },
    )
    assert response.status_code == 200, response.text
    full = report(alice, "sales", "?metric=amount").json()
    assert {r["currency"]: r["amount"] for r in full["items"]} == {"CNY": "10.00", "USD": "14.00"}
    fields = {f: "read" for f in RESOURCES["sales_orders"].fields}
    fields["unit_price"] = "hidden"
    assert change(admin, "sales_orders", actions=["read"], fields=fields).status_code == 200
    assert report(alice, "sales").json()["source_rows"] == 2
    assert report(alice, "sales", "?metric=amount").json()["items"] == []
    assert (
        report(alice, "sales", "/export?metric=amount").content.decode("utf-8-sig").count("\n") == 1
    )


def test_cross_user_order_scope_conditions_filters_and_revocation(env):
    admin, alice, bob, customers, _ = setup(env)
    sale_draft(alice, customers[0], quantity="1")
    sale_draft(bob, customers[1], quantity="9")
    assert report(alice, "sales").json()["source_rows"] == 1
    assert report(bob, "sales").json()["source_rows"] == 1
    assert report(admin, "sales").json()["source_rows"] == 2
    assert (
        change(
            admin,
            "sales_orders",
            actions=["report"],
            effect="deny",
            conditions=[{"field": "total", "op": "gt", "value": "5"}],
        ).status_code
        == 200
    )
    assert report(alice, "sales", "?currency=CNY").json()["items"] == []
    assert report(alice, "sales", "/export").content.decode("utf-8-sig").count("\n") == 1
    # Registry additions do not grant access to generic CRUD or arbitrary resources.
    assert report(admin, "users").status_code == 404
    assert alice.post("/api/v1/inventory_balances", json={"data": {}}).status_code in {
        403,
        404,
        405,
    }


@pytest.mark.parametrize(
    "name,query",
    [
        ("inventory", "?metric=amount"),
        ("inventory", "?status=draft"),
        ("sales", "?warehouse_id=unknown"),
        ("sales", "?currency=cny"),
        ("sales", "?status=received"),
        ("movements", "?kind=anything"),
        ("sales", "?metric=profit"),
        ("sales", "?role=admin"),
    ],
)
def test_filter_validation(env, name, query):
    admin = env["client"]()
    assert report(admin, name, query).status_code == 422


def test_caps_fail_closed_and_query_timeout_cleans_up(env, monkeypatch):
    admin, alice, _, customers, _ = setup(env)
    sale_draft(alice, customers[0])
    sale_draft(alice, customers[0])
    monkeypatch.setattr(reports, "SOURCE_LIMIT", 1)
    assert report(alice, "sales").json()["detail"] == "report_source_limit"
    monkeypatch.setattr(reports, "SOURCE_LIMIT", 10000)
    monkeypatch.setattr(reports, "GROUP_LIMIT", 0)
    assert report(alice, "sales", "/export").json()["detail"] == "report_group_limit"
    monkeypatch.setattr(reports, "GROUP_LIMIT", 200)
    if env["engine"].dialect.name == "sqlite":
        monkeypatch.setattr(reports, "QUERY_SECONDS", -1)
        # Make enough work to trigger SQLite's VM progress callback.
        with Session(env["engine"]) as db:
            from fastapi import HTTPException
            from sqlalchemy import text

            with pytest.raises(HTTPException) as error, reports.query_budget(db):
                db.execute(
                    text(
                        "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<100000) SELECT sum(x) FROM n"
                    )
                ).all()
            assert error.value.status_code == 503
            assert db.scalar(text("SELECT 1")) == 1
    else:
        from sqlalchemy import text

        with Session(env["engine"]) as db:
            before = db.scalar(text("SHOW statement_timeout"))
            with reports.query_budget(db):
                assert db.scalar(text("SHOW statement_timeout")) == "5s"
            assert db.scalar(text("SHOW statement_timeout")) == before


@pytest.mark.parametrize(
    "value", ["=1+1", "+SUM(1)", "-1+2", "@SUM(1)", " \t=1+1", "\ttext", "\ufeff=1"]
)
def test_csv_formula_injection(value):
    output = reports.csv_document({"columns": ["name"], "items": [{"name": value}]})
    assert list(csv.reader(io.StringIO(output.removeprefix("\ufeff"))))[1][0] == "'" + value
