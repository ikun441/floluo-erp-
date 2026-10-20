from conftest import PASSWORD, grant, post, product_rule
from erp.audit import verify
from erp.models import AuditEvent
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session


def test_auth_required_and_extra_identity_rejected(env):
    c = TestClient(env["app"])
    assert c.get("/api/v1/products").status_code == 401
    response = c.post(
        "/api/v1/auth/login", json={"username": "alice", "password": PASSWORD, "role": "admin"}
    )
    assert response.status_code == 422
    assert PASSWORD not in response.text


def test_default_deny_and_no_id_enumeration(env):
    alice = env["client"]("alice")
    assert alice.get("/api/v1/products").json() == {"items": []}
    assert alice.get("/api/v1/products/product-a").status_code == 404
    assert alice.get("/api/v1/products/product-b").status_code == 404


def test_own_scope_and_cross_role_writes(env):
    admin, alice, bob = env["client"](), env["client"]("alice"), env["client"]("bob")
    assert grant(admin, [product_rule()]).status_code == 200
    assert [r["id"] for r in alice.get("/api/v1/products").json()["items"]] == ["product-a"]
    assert [r["id"] for r in bob.get("/api/v1/products").json()["items"]] == ["product-b"]
    assert (
        post(
            alice, "/api/v1/products/product-b", {"version": 1, "data": {"name": "stolen"}}, "patch"
        ).status_code
        == 404
    )
    assert (
        post(
            alice,
            "/api/v1/products/product-a",
            {"version": 1, "data": {"name": "Updated"}},
            "patch",
        ).status_code
        == 200
    )
    assert alice.get("/api/v1/products/product-a").json()["name"] == "Updated"


def test_department_scope_with_missing_department_is_empty(env):
    admin, alice = env["client"](), env["client"]("alice")
    assert grant(admin, [product_rule(scope="department")]).status_code == 200
    assert len(alice.get("/api/v1/products").json()["items"]) == 1
    assert (
        post(
            admin, "/api/v1/users/alice", {"version": 1, "data": {"department_id": None}}, "patch"
        ).status_code
        == 200
    )
    assert alice.get("/api/v1/products").json()["items"] == []


def test_multiple_roles_explicit_deny_wins(env):
    admin, alice = env["client"](), env["client"]("alice")
    deny = product_rule(
        id="deny-second-role", subject={"kind": "role", "id": "second"}, effect="deny", scope="all"
    )
    res = grant(admin, [product_rule(), deny])
    assert res.status_code == 200 and res.json()["conflicts"]
    assert alice.get("/api/v1/products").json()["items"] == []


def test_field_projection_mask_and_update_rejection(env):
    admin, alice = env["client"](), env["client"]("alice")
    rule = product_rule(fields={"id": "read", "version": "read", "sku": "masked", "name": "write"})
    assert grant(admin, [rule]).status_code == 200
    row = alice.get("/api/v1/products/product-a").json()
    assert row["sku"] == "***" and "owner_id" not in row
    assert (
        post(
            alice, "/api/v1/products/product-a", {"version": 1, "data": {"unit": "secret"}}, "patch"
        ).status_code
        == 403
    )
    assert (
        post(
            alice,
            "/api/v1/products/product-a",
            {"version": 1, "data": {"name": "Permitted"}},
            "patch",
        ).status_code
        == 200
    )


def test_permission_revocation_takes_effect_in_existing_session(env):
    admin, alice = env["client"](), env["client"]("alice")
    assert grant(admin, [product_rule()]).status_code == 200
    assert alice.get("/api/v1/products").json()["items"]
    rev = admin.get("/api/v1/policies").json()
    assert (
        post(
            admin,
            "/api/v1/policies/publish",
            {
                "expected_revision": rev["number"],
                "rules": [r for r in rev["rules"] if r["id"] != "own-products"],
            },
        ).status_code
        == 200
    )
    assert alice.get("/api/v1/products").json()["items"] == []


def test_create_and_change_owner_cannot_escape_scope(env):
    admin, alice = env["client"](), env["client"]("alice")
    assert grant(admin, [product_rule()]).status_code == 200
    data = {
        "sku": "C",
        "name": "New",
        "unit": "piece",
        "owner_id": "bob",
        "department_id": "dept-a",
    }
    assert post(alice, "/api/v1/products", {"data": data}).status_code == 403
    data["owner_id"] = "alice"
    assert post(alice, "/api/v1/products", {"data": data}).status_code == 200
    assert (
        post(
            alice,
            "/api/v1/products/product-a",
            {"version": 1, "data": {"owner_id": "bob"}},
            "patch",
        ).status_code
        == 403
    )


def test_condition_blocks_transition_and_approval_blocks_execution(env):
    admin, alice = env["client"](), env["client"]("alice")
    rule = product_rule(conditions=[{"field": "active", "op": "eq", "value": True}])
    assert grant(admin, [rule]).status_code == 200
    assert (
        post(
            alice, "/api/v1/products/product-a", {"version": 1, "data": {"active": False}}, "patch"
        ).status_code
        == 403
    )
    assert grant(admin, [product_rule(id="approval", requires_approval=True)]).status_code == 200
    assert (
        post(
            alice,
            "/api/v1/products/product-a",
            {"version": 1, "data": {"name": "blocked"}},
            "patch",
        ).status_code
        == 403
    )


def test_csrf_origin_and_logout_revocation(env):
    admin = env["client"]()
    assert admin.post("/api/v1/roles", json={"data": {"name": "new"}}).status_code == 403
    assert (
        admin.post(
            "/api/v1/roles",
            json={"data": {"name": "new"}},
            headers={"origin": "http://evil", "x-csrf-token": admin.cookies["erp_csrf"]},
        ).status_code
        == 403
    )
    raw = admin.cookies.get("erp_session")
    assert post(admin, "/api/v1/auth/logout", {}).status_code == 200
    attacker = TestClient(env["app"])
    attacker.cookies.set("erp_session", raw)
    assert attacker.get("/api/v1/auth/me").status_code == 401


def test_disable_and_password_reset_revoke(env):
    admin, alice = env["client"](), env["client"]("alice")
    assert (
        post(
            admin,
            "/api/v1/users/alice",
            {"version": 1, "data": {"password": "New-fixture-" + "z" * 20}},
            "patch",
        ).status_code
        == 200
    )
    assert alice.get("/api/v1/auth/me").status_code == 401
    bob = env["client"]("bob")
    assert (
        post(
            admin, "/api/v1/users/bob", {"version": 1, "data": {"active": False}}, "patch"
        ).status_code
        == 200
    )
    assert bob.get("/api/v1/auth/me").status_code == 401


def test_stale_version_and_unique_conflict_rollback(env):
    admin = env["client"]()
    assert (
        post(
            admin, "/api/v1/products/product-a", {"version": 1, "data": {"name": "good"}}, "patch"
        ).status_code
        == 200
    )
    assert (
        post(
            admin, "/api/v1/products/product-a", {"version": 1, "data": {"name": "stale"}}, "patch"
        ).status_code
        == 409
    )
    assert (
        post(
            admin,
            "/api/v1/products/product-a",
            {"version": 2, "data": {"sku": "B", "name": "rollback"}},
            "patch",
        ).status_code
        == 409
    )
    row = admin.get("/api/v1/products/product-a").json()
    assert row["name"] == "good" and row["version"] == 2 and row["sku"] == "A"


def test_policy_schema_conflict_and_simulation(env):
    admin = env["client"]()
    assert (
        grant(
            admin, [product_rule(conditions=[{"field": "password_hash", "op": "eq", "value": "x"}])]
        ).status_code
        == 422
    )
    assert grant(admin, [product_rule()]).status_code == 200
    assert (
        post(admin, "/api/v1/policies/publish", {"expected_revision": 1, "rules": []}).status_code
        == 409
    )
    sim = post(
        admin,
        "/api/v1/policies/simulate",
        {"user_id": "alice", "resource": "products", "action": "read", "record_id": "product-a"},
    )
    assert sim.status_code == 200 and sim.json()["allowed"]
    alice = env["client"]("alice")
    assert (
        post(
            alice,
            "/api/v1/policies/simulate",
            {
                "user_id": env["admin_id"],
                "resource": "products",
                "action": "read",
                "record_id": "product-a",
            },
        ).status_code
        == 403
    )


def test_unauthorized_export_and_aggregate_no_fallback(env):
    alice = env["client"]("alice")
    assert alice.get("/api/v1/products/export").status_code == 404
    assert alice.get("/api/v1/reports").status_code == 404
    assert alice.get("/api/v1/audit").status_code == 404


def test_lockout_and_failed_login_audit(env):
    c = TestClient(env["app"])
    for _ in range(5):
        assert (
            c.post("/api/v1/auth/login", json={"username": "alice", "password": "bad"}).status_code
            == 401
        )
    assert (
        c.post("/api/v1/auth/login", json={"username": "alice", "password": PASSWORD}).status_code
        == 429
    )
    with Session(env["engine"]) as db:
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.event == "POST /api/v1/auth/login")
        ).all()
        assert [e.result for e in events] == [401] * 5 + [429]
        assert verify(db)


def test_audit_immutable_and_password_not_exposed(env):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    admin = env["client"]()
    assert PASSWORD not in admin.get("/api/v1/users").text
    assert "password_hash" not in admin.get("/api/v1/users").text
    with Session(env["engine"]) as db:
        assert verify(db)
        try:
            db.execute(text("UPDATE audit_event SET result=201"))
        except DBAPIError:
            db.rollback()
        else:
            raise AssertionError("audit update must fail")


def test_relationship_cycles_and_bad_reference(env):
    admin = env["client"]()
    assert (
        post(
            admin,
            "/api/v1/departments/dept-a",
            {"version": 1, "data": {"parent_id": "dept-a"}},
            "patch",
        ).status_code
        == 422
    )
    assert (
        post(
            admin,
            "/api/v1/users/alice",
            {"version": 1, "data": {"supervisor_id": "alice"}},
            "patch",
        ).status_code
        == 422
    )
    assert (
        post(
            admin,
            "/api/v1/users/alice",
            {"version": 1, "data": {"department_id": "unknown"}},
            "patch",
        ).status_code
        == 422
    )


def test_role_assignment_requires_separate_permission(env):
    admin, alice = env["client"](), env["client"]("alice")
    rule = {
        "id": "user-edit",
        "subject": {"kind": "user", "id": "alice"},
        "effect": "allow",
        "resource": "users",
        "actions": ["update"],
        "scope": "own",
        "fields": {"role_ids": "write"},
    }
    assert grant(admin, [rule]).status_code == 200
    with Session(env["engine"]) as db:
        from erp.models import UserRole

        admin_role = db.scalar(select(UserRole.role_id).where(UserRole.user_id == env["admin_id"]))
    assert (
        post(
            alice,
            "/api/v1/users/alice",
            {"version": 1, "data": {"role_ids": [admin_role]}},
            "patch",
        ).status_code
        == 403
    )
