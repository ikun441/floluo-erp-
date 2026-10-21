import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from conftest import grant, post
from erp import delivery_service as deliveries
from erp import message_gateway as gateway
from erp.audit import verify
from erp.business_models import PurchaseOrder
from erp.message_models import MessageDelivery, MessageInbox, MessageOperation, OneBotConnection
from erp.models import AuditEvent, now, uid
from erp.onebot.events import normalize_message_event
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_message_operations import ready
from test_messaging import allow_messages, bind, challenge, headers, instance, message, reply
from test_procurement import draft, rule


@pytest.mark.parametrize(
    "payload,outcome",
    [
        ({"status": "ok", "retcode": 0}, "delivered"),
        ({"status": "async", "retcode": 1}, "wait"),
        ({"status": "failed", "retcode": 1404}, "retry"),
        ({"status": "failed", "retcode": -1}, "retry"),
        ({"status": "ok", "retcode": True}, "invalid"),
        ({"status": "ok", "retcode": 0.0}, "invalid"),
        ({"status": "ok", "retcode": "0"}, "invalid"),
        ({"status": "async", "retcode": 0}, "invalid"),
        ({"status": "failed", "retcode": 0}, "invalid"),
        ({"retcode": 0}, "invalid"),
        ({"status": "unknown", "retcode": 0}, "invalid"),
    ],
)
def test_ack_outcomes_are_typed_and_fail_closed(payload, outcome):
    if outcome == "invalid":
        with pytest.raises(ValueError):
            deliveries.ack_outcome(payload)
    else:
        assert deliveries.ack_outcome(payload) == outcome


def connected(env):
    admin, buyer, values = ready(env)
    allow_messages(admin)
    row, token = instance(admin)
    bind(env, buyer, row, token)
    connection = gateway.open_connection(
        env["engine"], gateway.authenticate(env["engine"], row["id"], token, 10001)
    )
    return admin, buyer, values, row, token, connection


def queued(env, connection, text="查询采购订单", number=10):
    event = normalize_message_event(
        message(text, number), instance_id=connection.instance_id, expected_bot_id=10001
    )
    assert gateway.process(env["engine"], connection, event) is not None
    assert gateway.process(env["engine"], connection, event) is None
    with Session(env["engine"]) as db:
        row = db.scalar(select(MessageDelivery).where(MessageDelivery.event_key == event.event_key))
        assert row is not None
        return row.id, event


def body(action):
    return json.loads(action["params"]["message"][0]["data"]["text"])


def ack(action, status="ok", retcode=0):
    return {"echo": action["echo"], "status": status, "retcode": retcode}


def due(env, record_id):
    with Session(env["engine"]) as db:
        db.get(MessageDelivery, record_id).next_attempt_at = now() - timedelta(seconds=1)
        db.commit()


def test_queue_commits_once_and_ack_clears_recipe_without_storing_results(env):
    _, buyer, values, _, _, connection = connected(env)
    order = draft(buyer, values["supplier"])
    record_id, event = queued(env, connection)
    action = deliveries.claim(env["engine"], connection)
    assert body(action)["items"][0]["id"] == order["id"]
    with Session(env["engine"]) as db:
        row = db.get(MessageDelivery, record_id)
        assert row.recipe == {"kind": "query", "resource": "purchase_orders", "arguments": {}}
        assert row.attempts == 1 and row.state == "awaiting_ack"
        assert (
            db.scalar(
                select(func.count())
                .select_from(MessageDelivery)
                .where(MessageDelivery.event_key == event.event_key)
            )
            == 1
        )
    assert deliveries.acknowledge(env["engine"], connection, ack(action))
    assert not deliveries.acknowledge(env["engine"], connection, ack(action))
    with Session(env["engine"]) as db:
        row = db.get(MessageDelivery, record_id)
        assert row.recipe == {} and row.state == "delivered" and row.delivered_at
        assert row.attempt_token is None and verify(db)


def test_reconnect_retries_unconfirmed_reply_with_new_echo_and_no_business_reexecution(env):
    admin, buyer, values = ready(env)
    allow_messages(admin)
    row, token = instance(admin)
    bind(env, buyer, row, token)
    order = draft(buyer, values["supplier"])
    path = "/onebot/v11/ws/" + row["id"]
    payload = message("查询采购订单", 10)
    with buyer.websocket_connect(path, headers=headers(token)) as ws:
        ws.send_json(payload)
        first = ws.receive_json()  # Intentionally lost ACK.
        assert body(first)["items"][0]["id"] == order["id"]
    with buyer.websocket_connect(path, headers=headers(token)) as ws:
        resumed = ws.receive_json()
        assert first["echo"] != resumed["echo"] and body(first) == body(resumed)
        ws.send_json(ack(resumed))
        ws.send_json(payload)  # Duplicate business input produces no second queue row.
        assert reply(ws, message("查询采购订单", 11))["items"][0]["id"] == order["id"]
    event = normalize_message_event(payload, instance_id=row["id"], expected_bot_id=10001)
    with Session(env["engine"]) as db:
        result = db.scalar(
            select(MessageDelivery).where(MessageDelivery.event_key == event.event_key)
        )
        assert result.attempts == 2 and result.state == "delivered" and result.recipe == {}
        assert db.scalar(select(func.count()).select_from(PurchaseOrder)) == 1
        assert verify(db)


def test_retry_uses_current_projection_and_revocation_suppresses_old_reply(env):
    admin, buyer, values, _, _, connection = connected(env)
    order = draft(buyer, values["supplier"])
    record_id, _ = queued(env, connection)
    first = deliveries.claim(env["engine"], connection)
    assert "total" in body(first)["items"][0]
    assert deliveries.acknowledge(env["engine"], connection, ack(first, "failed", 1404))
    assert (
        grant(
            admin,
            [
                rule(
                    "purchase_orders",
                    id="delivery-id-only",
                    actions=["read"],
                    fields={"id": "read"},
                )
            ],
        ).status_code
        == 200
    )
    due(env, record_id)
    second = deliveries.claim(env["engine"], connection)
    assert body(second)["items"] == [{"id": order["id"]}]
    assert deliveries.acknowledge(env["engine"], connection, ack(second, "failed", 1404))
    assert (
        grant(
            admin, [rule("message_bindings", id="delivery-deny", effect="deny", actions=["use"])]
        ).status_code
        == 200
    )
    due(env, record_id)
    assert deliveries.claim(env["engine"], connection) is None
    with Session(env["engine"]) as db:
        row = db.get(MessageDelivery, record_id)
        assert row.state == "suppressed" and row.recipe == {} and row.attempts == 2


def test_timeout_async_backoff_attempt_limit_and_expiry_are_bounded(env):
    _, _, _, _, _, connection = connected(env)
    record_id, _ = queued(env, connection)
    first = deliveries.claim(env["engine"], connection)
    assert deliveries.acknowledge(env["engine"], connection, ack(first, "async", 1))
    assert deliveries.claim(env["engine"], connection) is None
    due(env, record_id)
    assert deliveries.claim(env["engine"], connection) is None
    with Session(env["engine"]) as db:
        row = db.get(MessageDelivery, record_id)
        assert row.state == "pending" and row.last_error == "ack_timeout"
        assert row.next_attempt_at.replace(tzinfo=now().tzinfo) > now()
    for expected in (2, 3):
        due(env, record_id)
        action = deliveries.claim(env["engine"], connection)
        assert action is not None
        assert not deliveries.acknowledge(env["engine"], connection, ack(first))
        assert deliveries.acknowledge(
            env["engine"],
            connection,
            {**ack(action, "failed", 1404), "message": "secret-provider-detail"},
        )
        with Session(env["engine"]) as db:
            row = db.get(MessageDelivery, record_id)
            assert row.attempts == expected
    due(env, record_id)
    assert deliveries.claim(env["engine"], connection) is None
    expired_id, _ = queued(env, connection, number=12)
    with Session(env["engine"]) as db:
        row = db.get(MessageDelivery, expired_id)
        row.expires_at = now() - timedelta(seconds=1)
        db.commit()
    assert deliveries.claim(env["engine"], connection) is None
    with Session(env["engine"]) as db:
        assert db.get(MessageDelivery, record_id).state == "failed"
        assert db.get(MessageDelivery, expired_id).state == "expired"
        assert db.get(MessageDelivery, expired_id).recipe == {}
        assert "secret-provider-detail" not in json.dumps(
            [r.details for r in db.scalars(select(AuditEvent))]
        )
        assert verify(db)


@pytest.mark.parametrize("change", ["revoke", "rebind", "disable"])
def test_delayed_business_reply_cannot_cross_binding_or_user_changes(env, change):
    admin, buyer, _, row, _, connection = connected(env)
    record_id, _ = queued(env, connection)
    if change in {"revoke", "rebind"}:
        binding = buyer.get("/api/v1/message_bindings").json()["items"][0]
        assert (
            post(
                buyer,
                "/api/v1/message_bindings/" + binding["id"] + "/revoke",
                {"version": binding["version"]},
            ).status_code
            == 200
        )
        if change == "rebind":
            command = challenge(buyer, row)
            event = normalize_message_event(
                message(command, 30), instance_id=row["id"], expected_bot_id=10001
            )
            assert gateway.process(env["engine"], connection, event)["status"] == "bound"
    else:
        user = admin.get("/api/v1/users/alice").json()
        assert (
            post(
                admin,
                "/api/v1/users/alice",
                {"version": user["version"], "data": {"active": False}},
                "patch",
            ).status_code
            == 200
        )
    action = deliveries.claim(env["engine"], connection)
    assert action is None or body(action)["status"] == "bound"
    with Session(env["engine"]) as db:
        assert db.get(MessageDelivery, record_id).state == "suppressed"
        assert db.get(MessageDelivery, record_id).recipe == {}


def test_lease_rejects_duplicates_and_old_connection_cannot_close_or_ack_new_one(env):
    _, _, _, row, token, old = connected(env)
    candidate = gateway.authenticate(env["engine"], row["id"], token, 10001)
    with pytest.raises(gateway.ConnectionRejected, match="already_active"):
        gateway.open_connection(env["engine"], candidate)
    with Session(env["engine"]) as db:
        db.scalar(select(OneBotConnection)).lease_expires_at = now() - timedelta(seconds=1)
        db.commit()
    new = gateway.open_connection(env["engine"], candidate)
    assert new.connection_id != old.connection_id
    gateway.close_connection(env["engine"], old)
    gateway.check_alive(env["engine"], new)
    with pytest.raises(gateway.ConnectionRejected):
        gateway.check_alive(env["engine"], old)
    with pytest.raises(gateway.ConnectionRejected):
        deliveries.acknowledge(env["engine"], old, {"status": "ok", "retcode": 0, "echo": uid()})
    with Session(env["engine"]) as db:
        runtime = db.scalar(select(OneBotConnection))
        assert runtime.connection_id == new.connection_id and runtime.state == "connected"


def test_ack_from_other_instance_or_wrong_echo_does_not_complete_delivery(env):
    admin, _, _, _, _, connection = connected(env)
    record_id, _ = queued(env, connection)
    action = deliveries.claim(env["engine"], connection)
    second, token = instance(admin, "second")
    other = gateway.open_connection(
        env["engine"], gateway.authenticate(env["engine"], second["id"], token, 10001)
    )
    assert not deliveries.acknowledge(env["engine"], other, ack(action))
    assert not deliveries.acknowledge(env["engine"], connection, {**ack(action), "echo": uid()})
    with Session(env["engine"]) as db:
        assert db.get(MessageDelivery, record_id).state == "awaiting_ack"
    assert deliveries.acknowledge(env["engine"], connection, ack(action))


def test_failed_enqueue_rolls_back_operation_inbox_and_delivery_atomically(env, monkeypatch):
    _, _, _, _, _, connection = connected(env)
    event = normalize_message_event(
        message("/erp 采购 新增 商品=product-a", 50),
        instance_id=connection.instance_id,
        expected_bot_id=10001,
    )
    original = deliveries.enqueue

    def failure(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("failure after durable reply write")

    monkeypatch.setattr(deliveries, "enqueue", failure)
    with pytest.raises(RuntimeError):
        gateway.process(env["engine"], connection, event)
    with Session(env["engine"]) as db:
        assert db.get(MessageInbox, event.event_key) is None
        assert (
            db.scalar(select(MessageDelivery).where(MessageDelivery.event_key == event.event_key))
            is None
        )
        assert db.scalar(select(func.count()).select_from(MessageOperation)) == 0
        assert verify(db)


def test_monitor_metadata_is_scoped_field_filtered_and_has_no_write_or_raw_body_api(env):
    admin, buyer, _, _, _, connection = connected(env)
    record_id, _ = queued(env, connection)
    assert buyer.get("/api/v1/message_deliveries").json()["items"] == []
    assert buyer.get("/api/v1/onebot_connections").json()["items"] == []
    assert grant(admin, [rule("message_deliveries"), rule("onebot_connections")]).status_code == 200
    runtime = buyer.get("/api/v1/onebot_connections").json()["items"][0]
    assert runtime["lease_expires_at"].endswith(("+00:00", "Z"))
    assert runtime["last_seen_at"].endswith(("+00:00", "Z"))
    result = buyer.get("/api/v1/message_deliveries").json()
    assert record_id in [r["id"] for r in result["items"]]
    for value in result["items"]:
        assert not set(value) & {
            "recipe",
            "recipient_id",
            "attempt_token",
            "attempt_connection_id",
            "event_key",
            "binding_id",
        }
    assert (
        post(buyer, "/api/v1/message_deliveries", {"data": {"state": "delivered"}}).status_code
        == 404
    )
    assert buyer.get("/api/v1/message_deliveries/" + record_id).status_code == 404
    assert (
        grant(
            admin,
            [
                rule(
                    "message_deliveries",
                    id="monitor-state-only",
                    actions=["read"],
                    fields={"state": "read"},
                )
            ],
        ).status_code
        == 200
    )
    assert all(set(r) == {"state"} for r in buyer.get("/api/v1/message_deliveries").json()["items"])
    assert buyer.get("/api/v1/message_deliveries?after=a").json()["items"] == []
    assert (
        grant(
            admin,
            [
                rule(
                    "onebot_instances",
                    id="monitor-hide-instance-id",
                    actions=["read"],
                    fields={"name": "read"},
                )
            ],
        ).status_code
        == 200
    )
    assert buyer.get("/api/v1/message_deliveries").json()["items"] == []
    assert buyer.get("/api/v1/onebot_connections").json()["items"] == []


def test_concurrent_claim_has_single_attempt_on_postgresql(env):
    if env["engine"].dialect.name != "postgresql":
        pytest.skip("real concurrent row locks require PostgreSQL")
    _, _, _, _, _, connection = connected(env)
    record_id, _ = queued(env, connection)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: deliveries.claim(env["engine"], connection), range(2)))
    assert sum(r is not None for r in results) == 1
    with Session(env["engine"]) as db:
        assert db.get(MessageDelivery, record_id).attempts == 1
        assert verify(db)
