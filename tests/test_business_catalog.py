import json

import pytest
from conftest import grant, post, product_rule
from erp.audit import verify
from erp.models import AuditEvent
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session


def rule(resource, **overrides):
    fields = {"id", "version", "name", "code", "owner_id", "department_id", "active"}
    if resource == "suppliers":
        fields |= {"contact", "phone"}
    return {
        "id": "own-" + resource,
        "subject": {"kind": "role", "id": "staff"},
        "resource": resource,
        "actions": ["read", "create", "update"],
        "scope": "own",
        "effect": "allow",
        "fields": {f: "write" for f in fields},
        **overrides,
    }


def create(client, resource, data):
    response = post(client, "/api/v1/" + resource, {"data": data})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("resource", ["suppliers", "warehouses"])
def test_new_catalog_scope_mask_write_and_paging(env, resource):
    admin, alice, bob = env["client"](), env["client"]("alice"), env["client"]("bob")
    for client, owner in ((admin, "alice"), (admin, "bob")):
        create(
            client,
            resource,
            {
                "code": owner,
                "name": owner,
                "owner_id": owner,
                "department_id": "dept-a" if owner == "alice" else "dept-b",
            },
        )
    policy = rule(resource)
    if resource == "suppliers":
        policy["fields"]["phone"] = "masked"
        policy["fields"]["contact"] = "hidden"
    assert grant(admin, [policy]).status_code == 200
    own = alice.get(f"/api/v1/{resource}?limit=1").json()["items"]
    assert len(own) == 1 and own[0]["owner_id"] == "alice"
    other = bob.get(f"/api/v1/{resource}").json()["items"][0]
    assert alice.get(f"/api/v1/{resource}/{other['id']}").status_code == 404
    assert (
        post(
            alice,
            f"/api/v1/{resource}/{other['id']}",
            {"version": 1, "data": {"name": "stolen"}},
            "patch",
        ).status_code
        == 404
    )
    assert (
        post(
            alice,
            f"/api/v1/{resource}/{own[0]['id']}",
            {"version": 1, "data": {"owner_id": "bob"}},
            "patch",
        ).status_code
        == 403
    )
    assert alice.get(f"/api/v1/{resource}?limit=1&after={own[0]['id']}").json()["items"] == []
    if resource == "suppliers":
        assert own[0]["phone"] == "***" and "contact" not in own[0]
        assert (
            post(
                alice,
                f"/api/v1/{resource}/{own[0]['id']}",
                {"version": 1, "data": {"phone": "private"}},
                "patch",
            ).status_code
            == 403
        )


def test_category_tree_reference_permissions_and_hidden_relation(env):
    admin, alice = env["client"](), env["client"]("alice")
    root = create(admin, "categories", {"name": "root"})
    child = create(admin, "categories", {"name": "child", "parent_id": root["id"]})
    assert (
        post(
            admin,
            "/api/v1/categories/" + root["id"],
            {"version": 1, "data": {"parent_id": child["id"]}},
            "patch",
        ).status_code
        == 422
    )
    assert grant(admin, [product_rule()]).status_code == 200
    for category in (root["id"], "nonexistent"):
        assert (
            post(
                alice,
                "/api/v1/products/product-a",
                {"version": 1, "data": {"category_id": category}},
                "patch",
            ).status_code
            == 404
        )
    assert (
        post(
            admin,
            "/api/v1/products/product-a",
            {"version": 1, "data": {"category_id": root["id"]}},
            "patch",
        ).status_code
        == 200
    )
    assert "category_id" not in alice.get("/api/v1/products/product-a").json()
    category_rule = {
        "id": "category-name-only",
        "subject": {"kind": "user", "id": "alice"},
        "resource": "categories",
        "actions": ["read"],
        "scope": "all",
        "effect": "allow",
        "fields": {"name": "read"},
    }
    assert grant(admin, [category_rule]).status_code == 200
    assert "category_id" not in alice.get("/api/v1/products/product-a").json()
    assert "parent_id" not in alice.get("/api/v1/categories/" + child["id"]).json()


def test_duplicate_code_and_stale_edit_roll_back(env):
    admin = env["client"]()
    row = create(admin, "suppliers", {"code": "unique", "name": "before", "owner_id": "alice"})
    assert (
        post(
            admin,
            "/api/v1/suppliers",
            {"data": {"code": "unique", "name": "duplicate", "owner_id": "bob"}},
        ).status_code
        == 409
    )
    assert (
        post(
            admin,
            "/api/v1/suppliers/" + row["id"],
            {"version": 1, "data": {"name": "after"}},
            "patch",
        ).status_code
        == 200
    )
    assert (
        post(
            admin,
            "/api/v1/suppliers/" + row["id"],
            {"version": 1, "data": {"name": "stale"}},
            "patch",
        ).status_code
        == 409
    )
    assert admin.get("/api/v1/suppliers/" + row["id"]).json()["name"] == "after"


def test_registry_requires_auth_and_new_resources_require_explicit_policy(env):
    assert TestClient(env["app"]).get("/api/v1/resource_catalog").status_code == 401
    admin, alice = env["client"](), env["client"]("alice")
    catalog = admin.get("/api/v1/resource_catalog").json()
    assert catalog["warehouses"]["actions"] == ["create", "read", "update"]
    assert "own" not in catalog["categories"]["scopes"]
    assert "category_id" in catalog["products"]["fields"]
    assert alice.get("/api/v1/suppliers").json() == {"items": []}
    assert (
        post(
            alice,
            "/api/v1/warehouses",
            {"data": {"code": "denied", "name": "denied", "owner_id": "alice"}},
        ).status_code
        == 403
    )
    assert post(admin, "/api/v1/inventory_balances", {"data": {"quantity": 10}}).status_code == 404
    assert post(admin, "/api/v1/purchase_orders", {"data": {}}).status_code == 404


def test_audit_summaries_are_bound_to_hash_and_redact_sensitive_values(env):
    admin = env["client"]()
    row = create(
        admin,
        "suppliers",
        {
            "code": "audit",
            "name": "safe",
            "owner_id": "alice",
            "phone": "private-phone",
            "contact": "private-contact",
        },
    )
    assert (
        post(
            admin,
            "/api/v1/suppliers/" + row["id"],
            {"version": 1, "data": {"name": "changed"}},
            "patch",
        ).status_code
        == 200
    )
    with Session(env["engine"]) as db:
        assert verify(db)
        event = db.scalar(
            select(AuditEvent)
            .where(AuditEvent.event == "PATCH /api/v1/{resource}/{record_id}")
            .order_by(AuditEvent.seq.desc())
        )
        assert event.details["record_id"] == row["id"]
        assert event.details["before"]["version"] == 1 and event.details["after"]["version"] == 2
        assert event.details["changed_fields"] == ["name"]
        assert event.details["before"]["fingerprint"] != event.details["after"]["fingerprint"]
        assert "private-phone" not in json.dumps(
            event.details
        ) and "private-contact" not in json.dumps(event.details)
        with db.no_autoflush:
            event.details = {"changed_fields": ["tampered"]}
            assert not verify(db)
        db.rollback()


def test_version_conditions_check_resulting_record_version(env):
    admin, alice = env["client"](), env["client"]("alice")
    assert (
        grant(
            admin, [product_rule(conditions=[{"field": "version", "op": "lte", "value": 1}])]
        ).status_code
        == 200
    )
    assert (
        post(
            alice,
            "/api/v1/products/product-a",
            {"version": 1, "data": {"name": "must-not-save"}},
            "patch",
        ).status_code
        == 403
    )
    assert admin.get("/api/v1/products/product-a").json()["version"] == 1
