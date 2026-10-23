import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from conftest import grant, post
from erp.ai_models import AIHandoff, AIRequest
from erp.audit import verify
from erp.business_models import PurchaseOrder
from erp.message_models import MessageOperation
from erp.models import AuditEvent, now
from erp.permissions import RESOURCES
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_ai import configure, execute, intent, parse, prepare
from test_ai import model_server as model_server
from test_message_operations import confirmation, ready
from test_procurement import rule


def setup_purchase(env, server):
    _, _, values = ready(env)
    admin, alice, _, _, _ = prepare(env, server)
    assert configure(admin, tools=["query_inventory", "prepare_purchase_draft"]).status_code == 200
    server.content = purchase(values)
    return admin, alice, values


def purchase(values, confidence=0.95):
    return intent(
        "purchase_orders",
        {k: v for k, v in values.items() if k not in {"product", "supplier"}},
        operation="create",
        references={k: v for k, v in values.items() if k in {"product", "supplier"}},
        confidence=confidence,
    )


def supplement(client, row, values, **changes):
    return post(
        client,
        "/api/v1/ai/requests/" + row["id"],
        {"version": row["version"], "values": values, **changes},
        "patch",
    )


def handoff(client, row):
    return post(
        client, "/api/v1/ai/requests/" + row["id"] + "/prepare", {"version": row["version"]}
    )


def counts(env):
    with Session(env["engine"]) as db:
        assert verify(db)
        return tuple(
            db.scalar(select(func.count()).select_from(model))
            for model in (AIHandoff, MessageOperation, PurchaseOrder)
        )


def test_multiround_local_completion_handoff_and_password_confirm_create_one_draft(
    env, model_server
):
    admin, alice, values = setup_purchase(env, model_server)
    model_server.content = purchase({"product": "Mouse A", "quantity": "3"})
    row = parse(alice).json()
    assert row["state"] == "clarification" and counts(env) == (0, 0, 0)
    assert handoff(alice, row).json()["detail"] == "ai_request_not_ready"
    first = supplement(alice, row, {"supplier": values["supplier"], "unit_price": "10.00"})
    assert first.status_code == 200, first.text
    assert first.json()["state"] == "clarification"
    final = supplement(alice, first.json(), {"currency": "CNY", "unit": "piece"})
    assert final.status_code == 200 and final.json()["state"] == "ready"
    row = final.json()
    assert execute(alice, row).json()["detail"] == "ai_write_preview_required"
    assert counts(env) == (0, 0, 0)
    result = handoff(alice, row)
    assert result.status_code == 200, result.text
    operation = result.json()["operation"]
    assert (
        operation["preview"]["total"] == "30.00" and operation["state"] == "awaiting_confirmation"
    )
    assert counts(env) == (1, 1, 0)
    replay = handoff(alice, row)
    assert replay.status_code == 200 and replay.json()["operation"]["id"] == operation["id"]
    assert handoff(alice, result.json()["request"]).status_code == 409
    assert (
        supplement(alice, result.json()["request"], {"quantity": "4"}).json()["detail"]
        == "ai_request_transferred"
    )
    assert (
        post(
            alice,
            "/api/v1/ai/requests/" + row["id"] + "/cancel",
            {"version": result.json()["request"]["version"]},
        ).status_code
        == 409
    )
    path = "/api/v1/message_operations/" + operation["id"] + "/confirm"
    assert post(alice, path, confirmation(operation, password="wrong")).status_code == 403
    # The user explicitly accepted parameters into an ordinary human workflow. AI availability is no longer required.
    assert configure(admin, enabled=False).status_code == 200
    response = post(alice, path, confirmation(operation))
    assert response.status_code == 200 and response.json()["result"]["status"] == "draft"
    assert (
        post(alice, path, confirmation(operation)).json()["result_id"]
        == response.json()["result_id"]
    )
    assert counts(env) == (1, 1, 1) and len(model_server.requests) == 1
    sent = model_server.requests[0]["body"]["messages"]
    assert len(sent) == 2 and sent[1]["content"] == "请帮我检查鼠标的可用情况，给出查询预览"
    assert values["supplier"] not in json.dumps(sent)
    with Session(env["engine"]) as db:
        order = db.scalar(select(PurchaseOrder))
        assert order.owner_id == "alice" and str(order.total) == "30.00"
        audits = db.scalars(select(AuditEvent).where(AuditEvent.event.like("%ai/requests%"))).all()
        assert values["supplier"] not in json.dumps([a.details for a in audits])


@pytest.mark.parametrize(
    "change",
    [
        "prepare_deny",
        "prepare_pending",
        "create_deny",
        "money_hidden",
        "own_scope",
        "reference_hidden",
        "ai_prepare_deny",
        "preview_hidden",
        "version_condition",
    ],
)
def test_handoff_checks_current_scopes_fields_and_policy_and_rolls_back(env, model_server, change):
    admin, alice, _ = setup_purchase(env, model_server)
    row = parse(alice).json()
    fields = {f: "write" for f in RESOURCES["purchase_orders"].fields}
    if change == "prepare_deny":
        deny = rule("ai_requests", id="deny-handoff", actions=["prepare"], effect="deny")
    elif change == "prepare_pending":
        deny = rule("purchase_orders", id="pending", actions=["ai_prepare"], requires_approval=True)
    elif change == "create_deny":
        deny = rule("purchase_orders", id="deny-create", actions=["create"], effect="deny")
    elif change == "money_hidden":
        fields["unit_price"] = "hidden"
        deny = rule("purchase_orders", id="hide-money", actions=["ai_prepare"], fields=fields)
    elif change == "own_scope":
        deny = rule(
            "purchase_orders",
            id="deny-alice",
            actions=["ai_prepare"],
            effect="deny",
            conditions=[{"field": "owner_id", "op": "eq", "value": "alice"}],
        )
    elif change == "reference_hidden":
        deny = rule("products", id="hide-reference", actions=["read"], effect="deny")
    elif change == "ai_prepare_deny":
        deny = rule("purchase_orders", id="deny-tool", actions=["ai_prepare"], effect="deny")
    elif change == "preview_hidden":
        deny = rule(
            "message_operations",
            id="hide-preview",
            actions=["read"],
            fields={"id": "read", "version": "read", "state": "read"},
        )
    else:
        deny = rule(
            "ai_requests",
            id="deny-new-version",
            actions=["prepare"],
            effect="deny",
            conditions=[{"field": "version", "op": "gte", "value": row["version"] + 1}],
        )
    assert grant(admin, [deny]).status_code == 200
    response = handoff(alice, row)
    assert response.status_code in {403, 404, 422}, response.text
    assert counts(env) == (0, 0, 0)
    assert alice.get("/api/v1/ai/requests/" + row["id"]).json()["version"] == row["version"]


@pytest.mark.parametrize(
    "kind",
    [
        "other_user",
        "new_session",
        "version",
        "expiry",
        "configuration",
        "cancelled",
        "tool_off",
        "low_confidence",
    ],
)
def test_source_session_state_config_and_confidence_are_current(env, model_server, kind):
    admin, alice, _ = setup_purchase(env, model_server)
    if kind == "low_confidence":
        model_server.content["confidence"] = 0.4
    row = parse(alice).json()
    if kind == "other_user":
        alice = env["client"]("bob")
    elif kind == "new_session":
        alice = env["client"]("alice")
    elif kind == "version":
        row = {**row, "version": 1}
    elif kind == "expiry":
        with Session(env["engine"]) as db:
            db.get(AIRequest, row["id"]).expires_at = now() - timedelta(seconds=1)
            db.commit()
    elif kind == "configuration":
        assert configure(admin, model="new-model").status_code == 200
    elif kind == "cancelled":
        assert (
            post(
                alice, "/api/v1/ai/requests/" + row["id"] + "/cancel", {"version": row["version"]}
            ).status_code
            == 200
        )
    elif kind == "tool_off":
        assert configure(admin, tools=["query_inventory"]).status_code == 200
    assert handoff(alice, row).status_code in {403, 404, 409, 410}
    assert supplement(alice, row, {"quantity": "4"}).status_code in {403, 404, 409, 410}
    assert counts(env) == (0, 0, 0)


@pytest.mark.parametrize(
    "values",
    [
        {"owner_id": "bob"},
        {"currency": "cny"},
        {"quantity": "0"},
        {"unit_price": "-1"},
        {"unit_price": "1.001"},
        {"product": ""},
        {"sql": "SELECT 1"},
        {"quantity": 3},
        {},
    ],
)
def test_supplement_rejects_untrusted_values_and_preserves_old_intent(env, model_server, values):
    _, alice, _ = setup_purchase(env, model_server)
    row = parse(alice).json()
    assert supplement(alice, row, values).status_code == 422
    current = alice.get("/api/v1/ai/requests/" + row["id"]).json()
    assert current["intent"] == row["intent"] and current["version"] == row["version"]
    assert counts(env) == (0, 0, 0)


def test_supplement_version_scope_field_and_round_limit(env, model_server):
    admin, alice, _ = setup_purchase(env, model_server)
    row = parse(alice).json()
    first = supplement(alice, row, {"quantity": "4"}).json()
    assert supplement(alice, row, {"quantity": "5"}).status_code == 409
    row = first
    for n in range(9):
        response = supplement(alice, row, {"quantity": str(n + 1)})
        assert response.status_code == 200, response.text
        row = response.json()
    assert supplement(alice, row, {"quantity": "11"}).json()["detail"] == "ai_supplement_limit"
    second = parse(alice, key="field-limit").json()
    fields = {f: "read" for f in RESOURCES["ai_requests"].fields}
    assert (
        grant(
            admin, [rule("ai_requests", id="readonly-intent", actions=["update"], fields=fields)]
        ).status_code
        == 200
    )
    assert supplement(alice, second, {"quantity": "5"}).status_code == 403
    assert len(model_server.requests) == 2


def test_current_reference_and_business_rights_still_checked_at_password_confirmation(
    env, model_server
):
    admin, alice, _ = setup_purchase(env, model_server)
    row = parse(alice).json()
    operation = handoff(alice, row).json()["operation"]
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
    path = "/api/v1/message_operations/" + operation["id"]
    assert post(alice, path + "/confirm", confirmation(operation)).status_code == 409
    fresh = alice.get(path).json()
    assert fresh["preview_digest"] != operation["preview_digest"]
    assert (
        grant(
            admin, [rule("purchase_orders", id="deny-final", actions=["create"], effect="deny")]
        ).status_code
        == 200
    )
    assert post(alice, path + "/confirm", confirmation(fresh)).status_code == 403
    assert counts(env) == (1, 1, 0)


def test_concurrent_same_source_handoff_has_one_pending_operation(env, model_server):
    if env["engine"].dialect.name != "postgresql":
        pytest.skip("requires real PostgreSQL row locks")
    _, alice, _ = setup_purchase(env, model_server)
    row = parse(alice).json()
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: handoff(alice, row), range(2)))
    assert [r.status_code for r in responses] == [200, 200]
    assert responses[0].json()["operation"]["id"] == responses[1].json()["operation"]["id"]
    assert counts(env) == (1, 1, 0) and len(model_server.requests) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"resource": "inventory"},
        {"operation": "approve"},
        {"references": {"product": "product-a", "owner_id": "bob"}},
        {"arguments": {"quantity": "3", "sql": "SELECT 1"}},
        {"arguments": {"currency": "cny"}},
        {"arguments": {"quantity": "NaN"}},
        {"arguments": {"unit": "x" * 31}},
    ],
)
def test_model_cannot_expand_purchase_intent_grammar(env, model_server, changes):
    _, alice, _ = setup_purchase(env, model_server)
    model_server.content.update(changes)
    response = parse(alice)
    assert response.status_code == 502 and response.json()["detail"] == "ai_response_invalid"
    assert counts(env) == (0, 0, 0)


def test_previous_policies_do_not_gain_purchase_AI_capabilities(env, model_server):
    admin, alice, _ = setup_purchase(env, model_server)
    current = admin.get("/api/v1/policies").json()
    rules = []
    for item in current["rules"]:
        item = dict(item)
        item["actions"] = [
            a
            for a in item["actions"]
            if a
            not in ({"prepare", "update"} if item["resource"] == "ai_requests" else {"ai_prepare"})
        ]
        if item["actions"]:
            rules.append(item)
    assert (
        post(
            admin,
            "/api/v1/policies/publish",
            {"expected_revision": current["number"], "rules": rules},
        ).status_code
        == 200
    )
    row = parse(alice).json()
    assert handoff(alice, row).status_code == 404
    assert supplement(alice, row, {"quantity": "4"}).status_code == 404
    assert counts(env) == (0, 0, 0)
