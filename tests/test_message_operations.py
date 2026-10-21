from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from conftest import PASSWORD, grant, post
from erp import message_operations, procurement
from erp.audit import verify
from erp.business_models import Outbox, PurchaseLine, PurchaseOrder
from erp.database import lock_gate
from erp.message_models import MessageBinding, MessageOperation
from erp.models import User, now
from erp.permissions import Engine, subject
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_messaging import allow_messages, bind, headers, instance, message, reply
from test_procurement import rule, setup


def ready(env):
    admin, buyer, supplier, _ = setup(env)
    assert grant(admin, [rule("message_operations")]).status_code == 200
    return (
        admin,
        buyer,
        {
            "product": "product-a",
            "supplier": supplier,
            "quantity": "3",
            "unit_price": "10.00",
            "currency": "CNY",
        },
    )


def create(client, values):
    response = post(client, "/api/v1/message_operations", {"values": values})
    assert response.status_code == 200, response.text
    return response.json()


def confirmation(row, **changes):
    return {
        "version": row["version"],
        "preview_digest": row["preview_digest"],
        "password": PASSWORD,
        **changes,
    }


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_collect_preview_password_confirm_and_replay_create_one_real_draft(env):
    _, buyer, values = ready(env)
    row = create(buyer, {"product": values["product"]})
    assert row["state"] == "collecting_missing" and "supplier" in row["missing_fields"]
    with Session(env["engine"]) as db:
        assert count(db, PurchaseOrder) == 0
    response = post(
        buyer,
        "/api/v1/message_operations/" + row["id"],
        {"version": row["version"], "values": values},
        "patch",
    )
    assert response.status_code == 200, response.text
    row = response.json()
    assert row["state"] == "awaiting_confirmation" and row["preview"]["total"] == "30.00"
    path = "/api/v1/message_operations/" + row["id"] + "/confirm"
    assert post(buyer, path, confirmation(row, password="wrong")).status_code == 403
    result = post(buyer, path, confirmation(row))
    assert result.status_code == 200, result.text
    assert result.json()["state"] == "completed" and result.json()["result"]["status"] == "draft"
    repeated = post(buyer, path, confirmation(row))
    assert (
        repeated.status_code == 200 and repeated.json()["result_id"] == result.json()["result_id"]
    )
    with Session(env["engine"]) as db:
        assert count(db, PurchaseOrder) == count(db, PurchaseLine) == count(db, Outbox) == 1
        assert db.scalar(select(PurchaseOrder)).owner_id == "alice"
        assert verify(db)


def test_old_previews_and_parameters_cannot_confirm_after_change(env):
    admin, buyer, values = ready(env)
    row = create(buyer, values)
    product = admin.get("/api/v1/products/product-a").json()
    assert (
        post(
            admin,
            "/api/v1/products/product-a",
            {"version": product["version"], "data": {"name": "renamed"}},
            "patch",
        ).status_code
        == 200
    )
    path = "/api/v1/message_operations/" + row["id"]
    assert post(buyer, path + "/confirm", confirmation(row)).status_code == 409
    fresh = buyer.get(path).json()
    assert fresh["version"] > row["version"] and fresh["preview_digest"] != row["preview_digest"]
    assert fresh["preview"]["product"]["name"] == "renamed"
    changed = post(
        buyer, path, {"version": fresh["version"], "values": {"quantity": "4"}}, "patch"
    ).json()
    assert changed["preview"]["total"] == "40.00"
    assert post(buyer, path + "/confirm", confirmation(fresh)).status_code == 409
    assert post(buyer, path + "/confirm", confirmation(changed)).status_code == 200


def test_owner_isolation_default_deny_spoofing_and_cursor_protection(env):
    admin, buyer, values = ready(env)
    row = create(buyer, values)
    bob = env["client"]("bob")
    assert (
        grant(
            admin,
            [
                rule(
                    "message_operations", id="bob-operations", subject={"kind": "user", "id": "bob"}
                )
            ],
        ).status_code
        == 200
    )
    path = "/api/v1/message_operations/" + row["id"]
    assert bob.get("/api/v1/message_operations").json()["items"] == []
    assert bob.get(path).status_code == 404
    assert post(bob, path + "/confirm", confirmation(row)).status_code == 404
    assert post(bob, path + "/cancel", {"version": row["version"]}).status_code == 404
    assert (
        post(buyer, "/api/v1/message_operations", {"owner_id": "bob", "values": values}).status_code
        == 422
    )
    assert (
        post(buyer, "/api/v1/message_operations", {"values": {"role": "admin"}}).status_code == 422
    )
    assert (
        post(buyer, "/api/v1/message_operations", {"values": {"quantity": 1.5}}).status_code == 422
    )
    assert (
        post(
            buyer, "/api/v1/message_operations", {"values": {**values, "currency": "cny"}}
        ).status_code
        == 422
    )
    assert (
        grant(
            admin,
            [
                rule(
                    "message_operations",
                    id="hide-op-id",
                    actions=["read"],
                    fields={"state": "read"},
                )
            ],
        ).status_code
        == 200
    )
    assert buyer.get("/api/v1/message_operations?after=" + row["id"]).json()["items"] == []


def test_cancel_and_expiry_never_create_business_records(env):
    _, buyer, values = ready(env)
    row = create(buyer, values)
    path = "/api/v1/message_operations/" + row["id"]
    assert post(buyer, path + "/cancel", {"version": row["version"]}).json()["state"] == "cancelled"
    assert post(buyer, path + "/confirm", confirmation(row)).status_code == 409
    expired = create(buyer, values)
    with Session(env["engine"]) as db:
        db.get(MessageOperation, expired["id"]).expires_at = now() - timedelta(seconds=1)
        db.commit()
    listed = buyer.get("/api/v1/message_operations?state=expired").json()["items"]
    assert [x["id"] for x in listed] == [expired["id"]]
    assert buyer.get("/api/v1/message_operations/" + expired["id"]).json()["state"] == "expired"
    assert (
        post(
            buyer, "/api/v1/message_operations/" + expired["id"] + "/confirm", confirmation(expired)
        ).status_code
        == 409
    )
    with Session(env["engine"]) as db:
        assert count(db, PurchaseOrder) == 0 and verify(db)


def test_permissions_rechecked_for_preview_confirmation_and_completed_replay(env):
    admin, buyer, values = ready(env)
    row = create(buyer, values)
    path = "/api/v1/message_operations/" + row["id"]
    assert (
        grant(
            admin,
            [
                rule(
                    "message_operations",
                    id="hide-preview",
                    actions=["read"],
                    fields={"id": "read", "version": "read", "state": "read"},
                )
            ],
        ).status_code
        == 200
    )
    hidden = buyer.get(path).json()
    assert "preview" not in hidden and "preview_digest" not in hidden
    assert post(buyer, path + "/confirm", confirmation(row)).status_code == 403
    with Session(env["engine"]) as db:
        assert count(db, PurchaseOrder) == 0


def test_completed_replay_projects_current_fields_and_requires_current_create_authority(env):
    admin, buyer, values = ready(env)
    row = create(buyer, values)
    path = "/api/v1/message_operations/" + row["id"] + "/confirm"
    assert post(buyer, path, confirmation(row)).status_code == 200
    assert (
        grant(
            admin,
            [rule("purchase_orders", id="read-id-only", actions=["read"], fields={"id": "read"})],
        ).status_code
        == 200
    )
    replay = post(buyer, path, confirmation(row))
    assert replay.status_code == 200 and replay.json()["result"] == {
        "id": replay.json()["result_id"]
    }
    assert (
        grant(
            admin,
            [rule("purchase_orders", id="deny-current-create", effect="deny", actions=["create"])],
        ).status_code
        == 200
    )
    assert post(buyer, path, confirmation(row)).status_code == 403
    with Session(env["engine"]) as db:
        assert count(db, PurchaseOrder) == 1


def test_reference_visibility_ambiguity_and_approval_cannot_be_bypassed(env):
    admin, buyer, values = ready(env)
    assert (
        grant(
            admin,
            [
                rule(
                    "purchase_orders",
                    id="requires-approval",
                    actions=["create"],
                    requires_approval=True,
                )
            ],
        ).status_code
        == 200
    )
    assert post(buyer, "/api/v1/message_operations", {"values": values}).status_code == 403
    with Session(env["engine"]) as db:
        assert count(db, MessageOperation) == count(db, PurchaseOrder) == 0


def test_onebot_collect_supplement_preview_then_web_confirmation(env):
    admin, buyer, values = ready(env)
    allow_messages(admin)
    bot, token = instance(admin)
    bind(env, buyer, bot, token)
    with buyer.websocket_connect("/onebot/v11/ws/" + bot["id"], headers=headers(token)) as ws:
        payload = message("/erp 采购 新增 商品=product-a", 2)
        row = reply(ws, payload)["operation"]
        assert row["state"] == "collecting_missing"
        ws.send_json(payload)
        text = f"/erp 补充 {row['id']} 供应商={values['supplier']} 数量=3 单价=10 币种=CNY"
        row = reply(ws, message(text, 3))["operation"]
        assert row["preview"]["total"] == "30.00"
        ack = reply(ws, message("/erp 确认 " + row["id"], 4))
        assert ack["status"] == "web_confirmation_required"
        with Session(env["engine"]) as db:
            assert count(db, PurchaseOrder) == 0 and count(db, MessageOperation) == 1
        assert (
            post(
                buyer, "/api/v1/message_operations/" + row["id"] + "/confirm", confirmation(row)
            ).status_code
            == 200
        )
        assert reply(ws, message("/erp 预览 " + row["id"], 5))["operation"]["state"] == "completed"


def test_revoked_and_rebound_platform_identity_cannot_revive_old_request(env):
    admin, buyer, values = ready(env)
    allow_messages(admin)
    bot, token = instance(admin)
    bind(env, buyer, bot, token)
    with buyer.websocket_connect("/onebot/v11/ws/" + bot["id"], headers=headers(token)) as ws:
        row = reply(
            ws,
            message(
                f"/erp 采购 新增 商品=product-a 供应商={values['supplier']} 数量=3 单价=10 币种=CNY",
                2,
            ),
        )["operation"]
    binding = buyer.get("/api/v1/message_bindings").json()["items"][0]
    assert (
        post(
            buyer,
            "/api/v1/message_bindings/" + binding["id"] + "/revoke",
            {"version": binding["version"]},
        ).status_code
        == 200
    )
    # Rebinding increments the persisted binding version; old previews stay unusable.
    from test_messaging import challenge

    command = challenge(buyer, bot)
    with buyer.websocket_connect("/onebot/v11/ws/" + bot["id"], headers=headers(token)) as ws:
        assert reply(ws, message(command, 3))["status"] == "bound"
    assert (
        post(
            buyer, "/api/v1/message_operations/" + row["id"] + "/confirm", confirmation(row)
        ).status_code
        == 403
    )
    with Session(env["engine"]) as db:
        assert db.get(MessageBinding, binding["id"]).version > 1
        assert count(db, PurchaseOrder) == 0
        from sqlalchemy import update
        from sqlalchemy.exc import DBAPIError

        with pytest.raises(DBAPIError):
            db.execute(
                update(MessageOperation)
                .where(MessageOperation.id == row["id"])
                .values(binding_version=None)
            )
        db.rollback()


def test_confirmation_rolls_back_order_operation_and_outbox_together(env, monkeypatch):
    _, buyer, values = ready(env)
    row = create(buyer, values)
    path = "/api/v1/message_operations/" + row["id"] + "/confirm"
    original = procurement.draft

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise HTTPException(409, "fixture_failure_after_draft")

    monkeypatch.setattr(procurement, "draft", fail)
    assert post(buyer, path, confirmation(row)).status_code == 409
    with Session(env["engine"]) as db:
        assert count(db, PurchaseOrder) == count(db, PurchaseLine) == count(db, Outbox) == 0
        assert db.get(MessageOperation, row["id"]).state == "awaiting_confirmation"
        assert verify(db)
    monkeypatch.setattr(procurement, "draft", original)
    assert post(buyer, path, confirmation(row)).status_code == 200


def test_simultaneous_confirmations_create_one_order(env):
    if env["engine"].dialect.name != "postgresql":
        pytest.skip("concurrent row locks require PostgreSQL")
    _, buyer, values = ready(env)
    row = create(buyer, values)

    def confirm(_):
        with Session(env["engine"]) as db:
            lock_gate(db)
            engine = Engine(db, subject(db, db.get(User, "alice")))
            operation = message_operations.load(db, engine, row["id"], "confirm")
            result = message_operations.confirm(
                db, engine, operation, row["version"], row["preview_digest"]
            )
            order_id = result.result_id
            db.commit()
            return order_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(confirm, range(2)))
    assert ids[0] == ids[1]
    with Session(env["engine"]) as db:
        assert count(db, PurchaseOrder) == 1 and verify(db)


def test_reference_resolution_requires_visible_unique_identity(env):
    admin, buyer, values = ready(env)
    response = post(
        admin,
        "/api/v1/products",
        {"data": {"sku": "extra", "name": "Mouse A", "unit": "piece", "owner_id": "alice"}},
    )
    assert response.status_code == 200
    assert (
        post(
            buyer, "/api/v1/message_operations", {"values": {**values, "product": "Mouse A"}}
        ).status_code
        == 422
    )
    assert (
        grant(
            admin, [rule("products", id="ids-only", actions=["read"], fields={"id": "read"})]
        ).status_code
        == 200
    )
    assert (
        post(
            buyer, "/api/v1/message_operations", {"values": {**values, "product": "A"}}
        ).status_code
        == 422
    )
    assert create(buyer, values)["preview"]["product"] == {"id": "product-a"}
    assert (
        post(
            buyer,
            "/api/v1/message_operations",
            {"values": {**values, "quantity": "0.0001", "unit_price": "0.01"}},
        ).status_code
        == 422
    )


def test_refresh_does_not_return_preview_after_operation_read_is_revoked_by_new_version(env):
    admin, buyer, values = ready(env)
    row = create(buyer, values)
    assert (
        grant(
            admin,
            [
                rule(
                    "message_operations",
                    id="deny-new-versions",
                    actions=["read"],
                    effect="deny",
                    conditions=[{"field": "version", "op": "gte", "value": 2}],
                )
            ],
        ).status_code
        == 200
    )
    product = admin.get("/api/v1/products/product-a").json()
    assert (
        post(
            admin,
            "/api/v1/products/product-a",
            {"version": product["version"], "data": {"name": "changed"}},
            "patch",
        ).status_code
        == 200
    )
    assert buyer.get("/api/v1/message_operations/" + row["id"]).status_code == 403
    with Session(env["engine"]) as db:
        assert db.get(MessageOperation, row["id"]).version == 1
        assert count(db, PurchaseOrder) == 0


def test_request_limit_and_destructive_downgrade_are_guarded(env):
    from alembic import command
    from alembic.config import Config

    _, buyer, _ = ready(env)
    for _ in range(20):
        assert create(buyer, {})["state"] == "collecting_missing"
    assert post(buyer, "/api/v1/message_operations", {"values": {}}).status_code == 429
    with pytest.raises(RuntimeError, match="message operations exist"):
        command.downgrade(Config("alembic.ini"), "8b7a6c5d4e3f")
