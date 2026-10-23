import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from conftest import grant, post
from erp.ai_models import AIConfiguration, AIRequest
from erp.audit import verify
from erp.models import AuditEvent, Base, User, now
from erp.permissions import RESOURCES
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_sales import draft as sale_draft
from test_sales import rule
from test_shipments import setup as stock_setup

TEXT = "请帮我检查鼠标的可用情况，给出查询预览"


def intent(resource="inventory", arguments=None, **changes):
    return {
        "operation": "query",
        "resource": resource,
        "arguments": arguments if arguments is not None else {"query": "Mouse"},
        "references": {},
        "confidence": 0.95,
        "parser_source": "ai",
        **changes,
    }


@pytest.fixture
def model_server():
    state = SimpleNamespace(
        content=intent(),
        status=200,
        requests=[],
        block=False,
        entered=threading.Event(),
        release=threading.Event(),
        delay=0,
        raw=None,
        finish_reason="stop",
        message_extra={},
    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("content-length", "0")))
            state.requests.append(
                {
                    "path": self.path,
                    "body": json.loads(body),
                    "authorization": self.headers.get("authorization"),
                }
            )
            state.entered.set()
            if state.block:
                state.release.wait(5)
            if state.delay:
                time.sleep(state.delay)
            message = {
                "content": state.content
                if isinstance(state.content, str)
                else json.dumps(state.content),
                **state.message_extra,
            }
            payload = (
                state.raw
                if state.raw is not None
                else json.dumps(
                    {"choices": [{"finish_reason": state.finish_reason, "message": message}]}
                ).encode()
            )
            try:
                self.send_response(state.status)
                self.send_header("Content-Type", "application/json")
                if state.status == 302:
                    self.send_header("Location", "/forbidden-redirect")
                self.end_headers()
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    state.url = "http://127.0.0.1:" + str(server.server_port) + "/v1"
    yield state
    state.release.set()
    server.shutdown()
    server.server_close()
    worker.join(timeout=2)


def configure(admin, **values):
    current = admin.get("/api/v1/ai/configuration").json()
    return post(
        admin,
        "/api/v1/ai/configuration",
        {"version": current["version"], "values": values},
        "patch",
    )


def prepare(env, server, stock=False):
    if stock:
        admin, alice, bob, customers, warehouse = stock_setup(env)
    else:
        admin, alice, bob = env["client"](), env["client"]("alice"), env["client"]("bob")
        customers, warehouse = [], None
    settings = env["app"].state.ai_settings
    settings.ai_allowed_base_urls = [server.url]
    settings.ai_api_key = SecretStr("Fixture-model-key")
    assert grant(admin, [rule("ai_requests")]).status_code == 200
    result = configure(
        admin,
        enabled=True,
        base_url=server.url,
        model="fixture-model",
        timeout_seconds=2,
        tools=["query_inventory", "query_purchase_orders", "query_sales_summary"],
    )
    assert result.status_code == 200, result.text
    return admin, alice, bob, customers, warehouse


def parse(client, key="parse-key", text=TEXT, **changes):
    return client.post(
        "/api/v1/ai/requests",
        headers={"X-CSRF-Token": client.cookies.get("erp_csrf", ""), "Idempotency-Key": key},
        json={"text": text, "consent": True, **changes},
    )


def execute(client, row):
    return post(
        client, "/api/v1/ai/requests/" + row["id"] + "/execute", {"version": row["version"]}
    )


def test_default_disabled_consent_auth_and_configuration_are_fail_closed(env, model_server):
    admin, alice = env["client"](), env["client"]("alice")
    assert admin.get("/api/v1/ai/configuration").json()["enabled"] is False
    assert parse(admin).json()["detail"] == "ai_disabled"
    assert parse(admin, consent=False).status_code == 422
    assert parse(admin, consent=1).status_code == 422
    assert parse(admin, user_id=env["admin_id"]).status_code == 422
    assert alice.get("/api/v1/ai/configuration").status_code == 403
    assert alice.get("/api/v1/ai/status").json() == {"enabled": False}
    for url in (
        model_server.url,
        "http://169.254.169.254/latest",
        "https://x:secret@example.com/v1",
        "https://example.com/v1?key=secret",
        "https://example.com/#fragment",
    ):
        assert configure(admin, base_url=url, enabled=True).status_code == 422
    assert model_server.requests == []
    assert admin.get("/api/v1/products").status_code == 200
    assert parse(admin, key="").status_code == 422


def test_real_parse_preview_current_query_and_private_idempotent_replay(env, model_server):
    admin, alice, bob, _, _ = prepare(env, model_server, stock=True)
    response = parse(alice)
    assert response.status_code == 200, response.text
    row = response.json()
    assert row["state"] == "ready" and row["intent"]["parser_source"] == "ai"
    assert parse(alice).json()["id"] == row["id"] and len(model_server.requests) == 1
    assert parse(alice, text=TEXT + "另一种描述").status_code == 409
    assert bob.get("/api/v1/ai/requests/" + row["id"]).status_code == 404
    result = execute(alice, row)
    assert result.status_code == 200, result.text
    assert result.json()["result"]["items"][0]["quantity"] == "10.0000"
    assert execute(alice, row).json() == result.json()  # Re-query, never re-run the model.
    assert len(model_server.requests) == 1
    captured = model_server.requests[0]
    assert captured["path"] == "/v1/chat/completions"
    assert captured["authorization"] == "Bearer Fixture-model-key"
    assert captured["body"]["messages"][1] == {"role": "user", "content": TEXT}
    sent = json.dumps(captured["body"])
    assert "Mouse A" not in sent and "10.0000" not in sent and "Fixture-model-key" not in sent
    assert "ai_allowed_base_urls" not in sent and "password" not in sent
    new_session = env["client"]("alice")
    assert new_session.get("/api/v1/ai/requests/" + row["id"]).status_code == 404
    assert parse(new_session).status_code == 404
    assert (
        parse(admin, key="local", text="查询一下Mouse还有多少库存。").json()["detail"]
        == "ai_local_available"
    )
    assert len(model_server.requests) == 1
    with Session(env["engine"]) as db:
        saved = db.get(AIRequest, row["id"])
        assert not hasattr(saved, "text") and saved.intent == intent()
        assert verify(db)
        audits = db.scalars(select(AuditEvent).where(AuditEvent.actor_id == "alice")).all()
        logged = json.dumps([item.details for item in audits])
        assert TEXT not in logged and "10.0000" not in logged and "Fixture-model-key" not in logged


@pytest.mark.parametrize("mode", ["hidden", "masked"])
def test_ai_query_field_constraints_never_expand_web_read(env, model_server, mode):
    admin, alice, _, _, _ = prepare(env, model_server, stock=True)
    row = parse(alice).json()
    fields = {field: "read" for field in RESOURCES["inventory_balances"].fields}
    fields["quantity"] = mode
    assert (
        grant(
            admin,
            [
                rule(
                    "inventory_balances",
                    id="ai-field-restriction",
                    scope="all",
                    actions=["ai_query"],
                    fields=fields,
                )
            ],
        ).status_code
        == 200
    )
    result = execute(alice, row).json()["result"]["items"][0]
    assert ("quantity" not in result) if mode == "hidden" else result["quantity"] == "***"
    assert alice.get("/api/v1/inventory_balances").json()["items"][0]["quantity"] == "10.0000"


@pytest.mark.parametrize("action", ["read", "ai_query"])
@pytest.mark.parametrize("restriction", ["deny", "approval"])
def test_explicit_deny_or_pending_on_either_tool_authority_filters_rows(
    env, model_server, action, restriction
):
    admin, alice, _, _, _ = prepare(env, model_server, stock=True)
    row = parse(alice).json()
    extra = {"effect": "deny"} if restriction == "deny" else {"requires_approval": True}
    assert (
        grant(
            admin,
            [rule("inventory_balances", id="ai-deny", scope="all", actions=[action], **extra)],
        ).status_code
        == 200
    )
    result = execute(alice, row)
    assert result.status_code == 200 and result.json()["result"]["items"] == []


def test_tool_requires_explicit_ai_capability_and_uses_owner_scope(env, model_server):
    admin, alice, bob, _, _ = prepare(env, model_server, stock=True)
    # Replace fixture dynamic grants with an explicit old role snapshot.
    revision = admin.get("/api/v1/policies").json()
    for policy in revision["rules"]:
        if policy["subject"].get("id") in {"staff", "alice"}:
            policy["actions"] = [action for action in policy["actions"] if action != "ai_query"]
    assert (
        post(
            admin,
            "/api/v1/policies/publish",
            {"expected_revision": revision["number"], "rules": revision["rules"]},
        ).status_code
        == 200
    )
    row = parse(alice).json()
    assert execute(alice, row).json()["detail"] == "ai_tool_denied"
    assert (
        grant(
            admin, [rule("inventory_balances", id="ai-own", actions=["ai_query"], scope="own")]
        ).status_code
        == 200
    )
    assert execute(alice, row).json()["result"]["items"][0]["quantity"] == "10.0000"
    other = parse(bob, key="bob").json()
    assert execute(bob, other).json()["result"]["items"] == []


def test_purchase_money_and_sales_aggregate_use_same_scopes(env, model_server):
    admin, alice, _, customers, _ = prepare(env, model_server, stock=True)
    model_server.content = intent("purchase_orders", {})
    row = parse(alice).json()
    fields = {field: "read" for field in RESOURCES["purchase_orders"].fields}
    fields["unit_price"] = "hidden"
    assert (
        grant(
            admin, [rule("purchase_orders", id="ai-money", actions=["ai_query"], fields=fields)]
        ).status_code
        == 200
    )
    result = execute(alice, row).json()["result"]["items"][0]
    assert "total" not in result and "unit_price" not in json.dumps(result)
    sale_draft(alice, customers[0])
    model_server.content = intent("sales_summary", {"metric": "amount", "currency": "CNY"})
    summary = parse(alice, key="summary").json()
    result = execute(alice, summary)
    assert result.status_code == 200, result.text
    assert result.json()["result"]["items"][0]["amount"] == "30.00"
    assert (
        grant(
            admin,
            [rule("sales_orders", id="ai-summary-denied", actions=["ai_query"], effect="deny")],
        ).status_code
        == 200
    )
    assert execute(alice, summary).json()["result"]["items"] == []


@pytest.mark.parametrize("change", ["configuration", "cancel", "expiry", "preview", "execute"])
def test_ready_requests_are_reauthorized_at_confirmation(env, model_server, change):
    admin, alice, _, _, _ = prepare(env, model_server)
    row = parse(alice).json()
    if change == "configuration":
        assert configure(admin, enabled=False).status_code == 200
    elif change == "cancel":
        assert (
            post(
                alice, "/api/v1/ai/requests/" + row["id"] + "/cancel", {"version": row["version"]}
            ).status_code
            == 200
        )
    elif change == "expiry":
        with Session(env["engine"]) as db:
            db.get(AIRequest, row["id"]).expires_at = now() - timedelta(seconds=1)
            db.commit()
    else:
        fields = {field: "read" for field in RESOURCES["ai_requests"].fields}
        fields["intent"] = "masked"
        assert (
            grant(
                admin,
                [
                    rule(
                        "ai_requests",
                        id="ai-preview",
                        actions=["read" if change == "preview" else "execute"],
                        fields=fields,
                    )
                ],
            ).status_code
            == 200
        )
    assert execute(alice, row).status_code in {403, 409, 410}
    assert len(model_server.requests) == 1


def test_low_confidence_and_unknown_properties_never_execute(env, model_server):
    _, alice, _, _, _ = prepare(env, model_server)
    model_server.content = intent(confidence=0.4)
    row = parse(alice).json()
    assert row["state"] == "clarification"
    assert execute(alice, row).json()["detail"] == "ai_request_not_ready"


@pytest.mark.parametrize(
    "malicious",
    [
        {"operation": "create"},
        {"resource": "users"},
        {"arguments": {"query": "Mouse", "sql": "SELECT * FROM erp_user"}},
        {"arguments": {"query": "Mouse", "user_id": "admin"}},
        {"references": {"role": "admin"}},
        {"confidence": float("nan")},
        {"confidence": 1.1},
        {"parser_source": "command"},
        {"arguments": {"query": 7}},
        {"arguments": {"query": ""}},
        {"unexpected": "ignored instructions"},
    ],
)
def test_untrusted_ai_structure_is_rejected_and_failed_state_is_audited(
    env, model_server, malicious
):
    _, alice, _, _, _ = prepare(env, model_server)
    model_server.content = intent(**malicious)
    response = parse(alice)
    assert response.status_code == 502 and response.json()["detail"] == "ai_response_invalid"
    records = alice.get("/api/v1/ai/requests").json()["items"]
    assert len(records) == 1 and records[0]["state"] == "failed" and records[0]["intent"] is None
    with Session(env["engine"]) as db:
        last = db.scalars(
            select(AuditEvent)
            .where(AuditEvent.event == "POST /api/v1/ai/requests")
            .order_by(AuditEvent.seq.desc())
        ).first()
        assert last.result == 502 and verify(db)


@pytest.mark.parametrize(
    "kind",
    [
        "duplicate",
        "truncated",
        "refusal",
        "tool_calls",
        "oversize",
        "status",
        "redirect",
        "timeout",
    ],
)
def test_http_and_response_failure_is_bounded_and_never_reflected(env, model_server, kind):
    admin, alice, _, _, _ = prepare(env, model_server)
    if kind == "duplicate":
        model_server.content = '{"operation":"query","operation":"create"}'
    elif kind == "truncated":
        model_server.finish_reason = "length"
    elif kind in {"refusal", "tool_calls"}:
        model_server.message_extra = {kind: "sensitive-upstream-detail"}
    elif kind == "oversize":
        model_server.raw = b"x" * 40000
    elif kind in {"status", "redirect"}:
        model_server.status = 503 if kind == "status" else 302
        model_server.raw = b"sensitive-upstream-detail"
    else:
        model_server.delay = 2.5
    before = time.monotonic()
    response = parse(alice)
    assert response.status_code == 502, response.text
    assert time.monotonic() - before < 4
    assert "sensitive-upstream-detail" not in response.text
    assert len(model_server.requests) == 1
    assert admin.get("/api/v1/products").status_code == 200
    assert alice.get("/api/v1/ai/requests").json()["items"][0]["state"] == "failed"


@pytest.mark.parametrize(
    "change", ["cancel", "configuration", "permission", "logout", "disabled_user"]
)
def test_model_io_releases_gate_and_completion_checks_current_authority(env, model_server, change):
    admin, alice, _, _, _ = prepare(env, model_server)
    model_server.block = True
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(parse, alice)
        try:
            assert model_server.entered.wait(2)
            before = time.monotonic()
            assert admin.get("/api/v1/products").status_code == 200
            assert (
                time.monotonic() - before < 1.5
            )  # Works on PostgreSQL and SQLite, while model waits.
            rows = alice.get("/api/v1/ai/requests").json()["items"]
            assert rows[0]["state"] == "parsing" and rows[0]["intent"] is None
            if change == "cancel":
                assert (
                    post(
                        alice, "/api/v1/ai/requests/" + rows[0]["id"] + "/cancel", {"version": 1}
                    ).status_code
                    == 200
                )
            elif change == "configuration":
                assert configure(admin, enabled=False).status_code == 200
            elif change == "permission":
                assert (
                    grant(
                        admin,
                        [
                            rule(
                                "ai_requests",
                                id="deny-completion",
                                actions=["create"],
                                effect="deny",
                            )
                        ],
                    ).status_code
                    == 200
                )
            elif change == "logout":
                assert post(alice, "/api/v1/auth/logout", {}).status_code == 200
            else:
                with Session(env["engine"]) as db:
                    db.get(User, "alice").active = False
                    db.commit()
        finally:
            model_server.release.set()
        response = future.result(timeout=4)
        assert response.status_code in {401, 403, 404, 409}, response.text
    with Session(env["engine"]) as db:
        assert db.scalar(select(AIRequest.intent)) is None
        assert verify(db)


def test_rate_limit_is_shared_and_stale_leases_release_capacity(env, model_server):
    admin, alice, _, _, _ = prepare(env, model_server)
    for number in range(5):
        assert parse(alice, key="rate-" + str(number)).status_code == 200
    assert parse(alice, key="rate-blocked").status_code == 429
    assert len(model_server.requests) == 5
    assert admin.get("/api/v1/products").status_code == 200


def test_ai_migration_metadata_and_history_downgrade_guard(env, model_server):
    admin, alice, _, _, _ = prepare(env, model_server)
    with env["engine"].connect() as connection:
        assert (
            compare_metadata(
                MigrationContext.configure(connection, opts={"compare_type": True}), Base.metadata
            )
            == []
        )
    # Empty requests allow explicit rollback; existing business schema remains untouched.
    command.downgrade(Config("alembic.ini"), "ce1a0b9c8d7e")
    command.upgrade(Config("alembic.ini"), "head")
    assert (
        configure(
            admin,
            enabled=True,
            base_url=model_server.url,
            model="fixture-model",
            tools=["query_inventory"],
        ).status_code
        == 200
    )
    assert parse(alice).status_code == 200
    with pytest.raises(RuntimeError, match="history"):
        command.downgrade(Config("alembic.ini"), "ce1a0b9c8d7e")
    with Session(env["engine"]) as db:
        assert db.scalar(select(func.count()).select_from(AIRequest)) == 1
        assert db.get(AIConfiguration, 1).enabled


def test_duplicate_inflight_key_and_enterprise_capacity_are_shared(env, model_server):
    admin, alice, bob, _, _ = prepare(env, model_server)
    model_server.block = True
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(parse, alice, "same-key")
        assert model_server.entered.wait(2)
        try:
            assert parse(alice, key="same-key").json()["detail"] == "ai_request_in_progress"
            second = pool.submit(parse, bob, "bob-key")
            deadline = time.monotonic() + 1.5
            while len(model_server.requests) < 2 and time.monotonic() < deadline:
                time.sleep(0.01)
            assert len(model_server.requests) == 2
            assert parse(admin, key="enterprise-blocked").json()["detail"] == "ai_rate_limited"
            assert parse(alice, key="other-key").status_code == 429
        finally:
            model_server.release.set()
        assert first.result(timeout=4).status_code == 200
        assert second.result(timeout=4).status_code == 200
    assert len(model_server.requests) == 2


def test_stale_inflight_replay_finishes_without_another_model_call(env, model_server):
    _, alice, _, _, _ = prepare(env, model_server)
    model_server.block = True
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(parse, alice, "stale-key")
        assert model_server.entered.wait(2)
        try:
            rows = alice.get("/api/v1/ai/requests").json()["items"]
            with Session(env["engine"]) as db:
                db.get(AIRequest, rows[0]["id"]).lease_expires_at = now() - timedelta(seconds=1)
                db.commit()
            replay = parse(alice, key="stale-key")
            assert replay.status_code == 200 and replay.json()["state"] == "failed"
            assert replay.json()["error_code"] == "ai_parse_expired"
        finally:
            model_server.release.set()
        assert first.result(timeout=4).status_code == 409
    assert len(model_server.requests) == 1


def test_csrf_and_hidden_preview_prevent_model_spend(env, model_server):
    admin, alice, _, _, _ = prepare(env, model_server)
    assert (
        alice.post(
            "/api/v1/ai/requests",
            json={"text": TEXT, "consent": True},
            headers={"Idempotency-Key": "no-csrf"},
        ).status_code
        == 403
    )
    fields = {field: "read" for field in RESOURCES["ai_requests"].fields}
    fields["intent"] = "hidden"
    assert (
        grant(
            admin, [rule("ai_requests", id="preview-before-spend", actions=["read"], fields=fields)]
        ).status_code
        == 200
    )
    assert parse(alice).json()["detail"] == "ai_preview_denied"
    assert model_server.requests == []


@pytest.mark.parametrize("kind", ["ai_schema", "malformed_json", "ordinary_schema"])
def test_early_validation_failures_are_audited_once_without_raw_input(env, kind):
    client = env["client"]("alice")
    headers = {"X-CSRF-Token": client.cookies["erp_csrf"], "Idempotency-Key": "validation-key"}
    marker = "sensitive-validation-fixture-never-log"
    if kind == "malformed_json":
        response = client.post(
            "/api/v1/ai/requests",
            content='{"text":"' + marker + '","consent":',
            headers={**headers, "Content-Type": "application/json"},
        )
    else:
        path = "/api/v1/ai/requests" if kind == "ai_schema" else "/api/v1/products"
        payload = {"text": marker, "consent": False} if kind == "ai_schema" else {"data": marker}
        response = client.post(path, json=payload, headers=headers)
    assert response.status_code == 422
    assert marker not in response.text
    with Session(env["engine"]) as db:
        rows = db.scalars(
            select(AuditEvent).where(AuditEvent.trace_id == response.headers["X-Trace-ID"])
        ).all()
        assert len(rows) == 1 and rows[0].result == 422 and rows[0].actor_id == "alice"
        assert marker not in json.dumps(rows[0].details) and verify(db)
