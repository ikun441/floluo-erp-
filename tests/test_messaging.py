import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from conftest import PASSWORD, grant, post
from erp import message_gateway
from erp.audit import digest, verify
from erp.message_models import (
    BindingChallenge,
    MessageBinding,
    MessageDelivery,
    MessageInbox,
    OneBotInstance,
)
from erp.models import AuditEvent, now
from erp.onebot.events import normalize_message_event
from erp.permissions import RESOURCES
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.websockets import WebSocketDisconnect
from test_procurement import approved, draft, receive, rule, setup


def instance(admin, name="test-bot"):
    result = post(admin, "/api/v1/onebot_instances", {"name": name, "bot_id": "10001"})
    assert result.status_code == 200, result.text
    return result.json()["instance"], result.json()["access_token"]


def allow_messages(admin, who="alice"):
    rules = [
        rule(
            "onebot_instances",
            id="instances-" + who,
            subject={"kind": "user", "id": who},
            actions=["read"],
            fields={f: "read" for f in RESOURCES["onebot_instances"].fields if f != "access_token"},
        ),
        rule("message_bindings", id="bindings-" + who, subject={"kind": "user", "id": who}),
    ]
    assert grant(admin, rules).status_code == 200


def challenge(client, row, platform="20002"):
    result = post(
        client,
        "/api/v1/message_binding_challenges",
        {"instance_id": row["id"], "platform_user_id": platform, "password": PASSWORD},
    )
    assert result.status_code == 200, result.text
    return result.json()["command"]


def message(text="/erp 采购 查询", message_id=1, user_id=20002, **extras):
    return {
        "time": 1,
        "self_id": 10001,
        "post_type": "message",
        "message_type": "private",
        "sub_type": "friend",
        "message_id": message_id,
        "user_id": user_id,
        "message": [{"type": "text", "data": {"text": text}}],
        **extras,
    }


def headers(token, **extras):
    return {
        "authorization": "Bearer " + token,
        "x-self-id": "10001",
        "x-client-role": "Universal",
        **extras,
    }


def reply(ws, payload):
    ws.send_json(payload)
    action = ws.receive_json()
    assert action["action"] == "send_private_msg"
    assert action["params"]["user_id"] == payload["user_id"]
    with Session(ws.app.state.engine) as db:
        delivery_id = db.scalar(
            select(MessageDelivery.id).where(MessageDelivery.attempt_token == action["echo"])
        )
    assert delivery_id is not None
    ws.send_json({"status": "ok", "retcode": 0, "echo": action["echo"], "data": {"message_id": 1}})
    # ACK persistence is an explicit barrier before the test may immediately disconnect.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with Session(ws.app.state.engine) as db:
            if db.get(MessageDelivery, delivery_id).state == "delivered":
                break
        time.sleep(0.01)
    else:
        pytest.fail("OneBot API acknowledgment was not durably recorded")
    return json.loads(action["params"]["message"][0]["data"]["text"])


def bind(env, client, row, token):
    command = challenge(client, row)
    with client.websocket_connect("/onebot/v11/ws/" + row["id"], headers=headers(token)) as ws:
        assert reply(ws, message(command))["status"] == "bound"
    return command


def test_connection_authentication_and_credential_secrecy(env):
    admin = env["client"]()
    row, token = instance(admin)
    listing = admin.get("/api/v1/onebot_instances").text
    assert token not in listing and "token_digest" not in listing and "access_token" not in listing
    for kwargs in [
        headers("x" * 43),
        headers(token, **{"x-self-id": "10002"}),
        headers(token, **{"x-client-role": "Event"}),
        headers(token, origin="https://other"),
    ]:
        with pytest.raises(WebSocketDisconnect):
            with admin.websocket_connect("/onebot/v11/ws/" + row["id"], headers=kwargs):
                pass
    with Session(env["engine"]) as db:
        assert db.get(OneBotInstance, row["id"]).token_digest == digest(token)
        assert verify(db)


def test_binding_websocket_query_and_web_have_identical_scopes(env):
    admin, buyer, supplier, _ = setup(env)
    allow_messages(admin)
    row, token = instance(admin)
    own = draft(buyer, supplier)
    # Other user's order exists but must remain absent on both Web and OneBot.
    post(
        admin,
        "/api/v1/purchase_orders",
        {
            "supplier_id": supplier,
            "currency": "CNY",
            "lines": [{"product_id": "product-b", "quantity": "1", "unit_price": "99"}],
        },
    )
    command = challenge(buyer, row)
    path = "/onebot/v11/ws/" + row["id"]
    with buyer.websocket_connect(path, headers=headers(token)) as ws:
        assert reply(ws, message(command, user_id=99999))["status"] == "denied"
        assert reply(ws, message(command, 2))["status"] == "bound"
        assert reply(ws, message(command, 3))["status"] == "denied"
        result = reply(ws, message(message_id=4, sender={"role": "owner", "user_id": 99999}))
        assert result["items"] == buyer.get("/api/v1/purchase_orders").json()["items"]
        assert [r["id"] for r in result["items"]] == [own["id"]]
        # Private-only processing: no response to a group event; next private event still works.
        ws.send_json(message(message_id=5, message_type="group", sub_type="normal", group_id=88))
        assert reply(ws, message(message_id=6))["items"] == result["items"]
    with Session(env["engine"]) as db:
        assert db.scalar(select(func.count()).select_from(MessageBinding)) == 1
        assert all(r.consumed for r in db.scalars(select(BindingChallenge)))
        assert command.split()[-1] not in str([r.details for r in db.scalars(select(AuditEvent))])
        assert verify(db)


def test_bindings_default_deny_reauthentication_and_single_challenge(env):
    admin, buyer = env["client"](), env["client"]("alice")
    row, token = instance(admin)
    body = {"instance_id": row["id"], "platform_user_id": "20002", "password": PASSWORD}
    assert post(buyer, "/api/v1/message_binding_challenges", body).status_code == 404
    allow_messages(admin)
    assert (
        post(buyer, "/api/v1/message_binding_challenges", {**body, "owner_id": "bob"}).status_code
        == 422
    )
    assert (
        post(buyer, "/api/v1/message_binding_challenges", {**body, "password": "wrong"}).status_code
        == 403
    )
    first, second = challenge(buyer, row), challenge(buyer, row)
    with buyer.websocket_connect("/onebot/v11/ws/" + row["id"], headers=headers(token)) as ws:
        assert reply(ws, message(first))["status"] == "denied"
        assert reply(ws, message(second, 2))["status"] == "bound"
    binding = buyer.get("/api/v1/message_bindings").json()["items"][0]
    bob = env["client"]("bob")
    allow_messages(admin, "bob")
    assert bob.get("/api/v1/message_bindings").json()["items"] == []
    assert (
        post(
            bob, "/api/v1/message_bindings/" + binding["id"] + "/revoke", {"version": 1}
        ).status_code
        == 404
    )
    assert (
        post(
            buyer, "/api/v1/message_bindings/" + binding["id"] + "/revoke", {"version": 1}
        ).status_code
        == 200
    )
    with buyer.websocket_connect("/onebot/v11/ws/" + row["id"], headers=headers(token)) as ws:
        assert reply(ws, message(message_id=3))["status"] == "binding_required"


def test_revocation_rotation_and_disable_invalidate_connected_clients(env):
    admin, buyer = env["client"](), env["client"]("alice")
    allow_messages(admin)
    row, token = instance(admin)
    bind(env, buyer, row, token)
    with buyer.websocket_connect("/onebot/v11/ws/" + row["id"], headers=headers(token)) as ws:
        assert reply(ws, message(message_id=2))["items"] == []
        assert (
            grant(
                admin, [rule("message_bindings", id="deny-use", effect="deny", actions=["use"])]
            ).status_code
            == 200
        )
        assert reply(ws, message(message_id=3))["status"] == "denied"
        rotated = post(
            admin, "/api/v1/onebot_instances/" + row["id"] + "/rotate_token", {"version": 1}
        ).json()
        ws.send_json(message(message_id=4))
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
    with buyer.websocket_connect(
        "/onebot/v11/ws/" + row["id"], headers=headers(rotated["access_token"])
    ) as ws:
        assert (
            post(
                admin,
                "/api/v1/onebot_instances/" + row["id"],
                {"version": 2, "active": False},
                "patch",
            ).status_code
            == 200
        )
        ws.send_json(message(message_id=5))
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_inventory_tool_uses_same_projections_and_masks(env):
    admin, buyer, warehouse, order = approved(env)
    assert receive(buyer, order, warehouse).status_code == 200
    allow_messages(admin)
    row, token = instance(admin)
    bind(env, buyer, row, token)
    with buyer.websocket_connect("/onebot/v11/ws/" + row["id"], headers=headers(token)) as ws:
        result = reply(ws, message("/erp 库存 查询 'Mouse A'", 2))
        assert result["items"] == buyer.get("/api/v1/inventory_balances").json()["items"]
        assert result["items"][0]["quantity"] == "3.0000"
        assert (
            grant(
                admin,
                [
                    rule(
                        "inventory_balances",
                        id="mask-stock",
                        fields={"id": "read", "quantity": "masked"},
                    )
                ],
            ).status_code
            == 200
        )
        masked = reply(ws, message("/erp 库存 查询 'Mouse A'", 3))
        assert masked["items"][0]["quantity"] == "***"
        assert (
            grant(
                admin,
                [
                    rule(
                        "products",
                        id="hide-name",
                        scope="all",
                        actions=["read"],
                        fields={"id": "read"},
                    )
                ],
            ).status_code
            == 200
        )
        assert reply(ws, message("/erp 库存 查询 'Mouse A'", 4))["items"] == []


def test_durable_replay_collision_expiry_and_no_message_writes(env):
    admin, buyer = env["client"](), env["client"]("alice")
    allow_messages(admin)
    row, token = instance(admin)
    command = challenge(buyer, row)
    with Session(env["engine"]) as db:
        ch = db.scalar(select(BindingChallenge))
        ch.expires_at = now() - timedelta(seconds=1)
        db.commit()
    conn = message_gateway.authenticate(env["engine"], row["id"], token, 10001)

    def normalized(payload):
        return normalize_message_event(payload, instance_id=row["id"], expected_bot_id=10001)

    assert (
        message_gateway.process(env["engine"], conn, normalized(message(command)))["status"]
        == "denied"
    )
    assert message_gateway.process(env["engine"], conn, normalized(message(command))) is None
    with pytest.raises(message_gateway.ConnectionRejected):
        message_gateway.process(env["engine"], conn, normalized(message("altered")))
    command = challenge(buyer, row)
    assert (
        message_gateway.process(env["engine"], conn, normalized(message(command, 2)))["status"]
        == "bound"
    )
    create = message("/erp 采购 新增 商品=mouse 数量=2 单价=5 供应商=s 币种=CNY", 3)
    assert message_gateway.process(env["engine"], conn, normalized(create))["status"] == "denied"
    with Session(env["engine"]) as db:
        assert db.scalar(select(func.count()).select_from(MessageInbox)) == 3
        assert verify(db)


def test_concurrent_duplicate_message_has_one_result(env):
    if env["engine"].dialect.name != "postgresql":
        pytest.skip("real concurrent row locks require PostgreSQL")
    admin, buyer = env["client"](), env["client"]("alice")
    allow_messages(admin)
    row, token = instance(admin)
    command = challenge(buyer, row)
    conn = message_gateway.authenticate(env["engine"], row["id"], token, 10001)
    event = normalize_message_event(message(command), instance_id=row["id"], expected_bot_id=10001)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: message_gateway.process(env["engine"], conn, event), range(2))
        )
    assert sum(r is not None for r in results) == 1
    with Session(env["engine"]) as db:
        assert db.scalar(select(func.count()).select_from(MessageBinding)) == 1
        assert db.scalar(select(func.count()).select_from(MessageInbox)) == 1


def test_read_approval_flags_block_web_and_message_results(env):
    admin, buyer, supplier, _ = setup(env)
    allow_messages(admin)
    draft(buyer, supplier)
    row, token = instance(admin)
    bind(env, buyer, row, token)
    assert (
        grant(
            admin,
            [
                rule(
                    "purchase_orders",
                    id="approval-needed",
                    actions=["read"],
                    requires_approval=True,
                )
            ],
        ).status_code
        == 200
    )
    assert buyer.get("/api/v1/purchase_orders").json()["items"] == []
    with buyer.websocket_connect("/onebot/v11/ws/" + row["id"], headers=headers(token)) as ws:
        assert reply(ws, message(message_id=2))["items"] == []


def test_failed_processing_rolls_back_binding_and_allows_safe_replay(env, monkeypatch):
    from erp import message_service

    admin, buyer = env["client"](), env["client"]("alice")
    allow_messages(admin)
    row, token = instance(admin)
    command = challenge(buyer, row)
    event = normalize_message_event(message(command), instance_id=row["id"], expected_bot_id=10001)
    conn = message_gateway.authenticate(env["engine"], row["id"], token, 10001)
    original = message_service.dispatch

    def failure(db, event):
        original(db, event)
        raise RuntimeError("test failure after binding write")

    monkeypatch.setattr(message_service, "dispatch", failure)
    with pytest.raises(RuntimeError):
        message_gateway.process(env["engine"], conn, event)
    with Session(env["engine"]) as db:
        assert db.scalar(select(func.count()).select_from(MessageBinding)) == 0
        assert db.scalar(select(func.count()).select_from(MessageInbox)) == 0
        assert not db.scalar(select(BindingChallenge)).consumed
        assert db.scalar(select(AuditEvent).order_by(AuditEvent.seq.desc())).result == 500
        assert verify(db)
    monkeypatch.setattr(message_service, "dispatch", original)
    assert message_gateway.process(env["engine"], conn, event)["status"] == "bound"


def test_reverse_websocket_over_actual_loopback_network(env):
    import socket
    import threading
    import time

    import uvicorn
    from websockets.sync.client import connect

    admin, buyer = env["client"](), env["client"]("alice")
    allow_messages(admin)
    row, token = instance(admin)
    command = challenge(buyer, row)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    config = uvicorn.Config(env["app"], log_level="error", access_log=False, ws_max_size=65536)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        with connect(
            f"ws://127.0.0.1:{port}/onebot/v11/ws/{row['id']}",
            additional_headers=headers(token),
            proxy=None,
            open_timeout=5,
        ) as ws:
            ws.send(json.dumps(message(command)))
            action = json.loads(ws.recv(timeout=5))
            body = json.loads(action["params"]["message"][0]["data"]["text"])
            assert body["status"] == "bound"
            ws.send(
                json.dumps(
                    {"post_type": "notice", "self_id": 10001, "notice_type": "group_increase"}
                )
            )
            # A duplicate binding event has no reply; a later query confirms the socket is live.
            ws.send(json.dumps(message(command)))
            ws.send(json.dumps(message(message_id=2)))
            response = json.loads(ws.recv(timeout=5))
            assert json.loads(response["params"]["message"][0]["data"]["text"])["items"] == []
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive()


def test_inbox_is_immutable_and_schema_has_no_missing_migration(env):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    admin = env["client"]()
    row, token = instance(admin)
    conn = message_gateway.authenticate(env["engine"], row["id"], token, 10001)
    event = normalize_message_event(message(), instance_id=row["id"], expected_bot_id=10001)
    message_gateway.process(env["engine"], conn, event)
    for statement in ("DELETE FROM message_inbox", "UPDATE message_inbox SET result='changed'"):
        with Session(env["engine"]) as db:
            with pytest.raises(DBAPIError):
                db.execute(text(statement))
            db.rollback()
    command.check(Config("alembic.ini"))
    with pytest.raises(RuntimeError, match="message data exists"):
        command.downgrade(Config("alembic.ini"), "5a6ef43a4a48")


def test_message_rate_limits_and_disabled_users_fail_closed(env):
    admin, buyer = env["client"](), env["client"]("alice")
    allow_messages(admin)
    row, token = instance(admin)
    bind(env, buyer, row, token)
    conn = message_gateway.authenticate(env["engine"], row["id"], token, 10001)
    for index in range(2, 31):
        event = normalize_message_event(
            message(message_id=index), instance_id=row["id"], expected_bot_id=10001
        )
        assert message_gateway.process(env["engine"], conn, event)["items"] == []
    event = normalize_message_event(
        message(message_id=31), instance_id=row["id"], expected_bot_id=10001
    )
    assert message_gateway.process(env["engine"], conn, event) is None
    with Session(env["engine"]) as db:
        assert db.get(MessageInbox, event.event_key).result == "rate_limited"
    # A different fresh instance has a separate budget; disabled ERP users still cannot use it.
    second, token2 = instance(admin, "second-bot")
    command = challenge(buyer, second)
    conn2 = message_gateway.authenticate(env["engine"], second["id"], token2, 10001)
    bound_event = normalize_message_event(
        message(command), instance_id=second["id"], expected_bot_id=10001
    )
    assert message_gateway.process(env["engine"], conn2, bound_event)["status"] == "bound"
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
    event = normalize_message_event(
        message(message_id=2), instance_id=second["id"], expected_bot_id=10001
    )
    assert message_gateway.process(env["engine"], conn2, event)["status"] == "denied"


def test_challenge_reauthentication_is_rate_limited_and_locks_failed_passwords(env):
    admin, buyer = env["client"](), env["client"]("alice")
    allow_messages(admin)
    row, _ = instance(admin)
    body = {"instance_id": row["id"], "platform_user_id": "20002", "password": "incorrect"}
    for _ in range(5):
        assert post(buyer, "/api/v1/message_binding_challenges", body).status_code == 403
    assert (
        post(
            buyer, "/api/v1/message_binding_challenges", {**body, "password": PASSWORD}
        ).status_code
        == 429
    )
    with Session(env["engine"]) as db:
        from erp.models import User

        user = db.get(User, "alice")
        assert user.failed_logins == 5 and user.locked_until is not None
        assert db.scalar(select(func.count()).select_from(BindingChallenge)) == 0
        assert verify(db)
