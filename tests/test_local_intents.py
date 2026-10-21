"""Offline rules never bypass the existing preview, identity or authorization boundary."""

import json

import pytest
from conftest import grant, post, product_rule
from erp import message_gateway
from erp.audit import verify
from erp.business_models import Outbox, PurchaseOrder
from erp.local_parser import parse_message
from erp.message_models import MessageOperation
from erp.models import AuditEvent
from erp.onebot.events import normalize_message_event
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_message_operations import confirmation, count, ready
from test_messaging import allow_messages, bind, headers, instance, message, reply
from test_procurement import approved, draft, receive, rule


@pytest.mark.parametrize(
    "text,query",
    [
        ("查询一下鼠标还有多少库存。", "鼠标"),
        ("请帮我查询鼠标库存", "鼠标"),
        ("鼠标还有多少库存？", "鼠标"),
        ('查询"Mouse A"库存', "Mouse A"),
        ("查询“鼠标和键盘”库存", "鼠标和键盘"),
    ],
)
def test_local_inventory_extraction(text, query):
    result = parse_message(text)
    assert result.intent.operation == "query"
    assert result.intent.resource == "inventory"
    assert result.intent.arguments == {"query": query}
    assert result.intent.parser_source == "local_rule"
    assert result.intent.references == {} and result.missing == ()


def test_local_purchase_preserves_exact_decimals_units_and_missing_currency():
    result = parse_message("登记采购20个鼠标，每个35元。")
    assert result.intent.arguments == {"quantity": "20", "unit_price": "35", "unit": "个"}
    assert result.intent.references == {"product": "鼠标"}
    assert result.missing == ("supplier", "currency")
    full = parse_message('采购2.5件"Mouse A"，单价12.50元，供应商="Supplier A"，币种=CNY。')
    assert full.intent.arguments == {
        "quantity": "2.5",
        "unit_price": "12.50",
        "unit": "件",
        "currency": "CNY",
    }
    assert full.intent.references == {"product": "Mouse A", "supplier": "Supplier A"}
    assert not full.missing and full.intent.confidence == 0.9
    assert parse_message("查询采购订单 PO-123").intent.arguments == {"number": "PO-123"}
    assert parse_message("查询采购订单").intent.arguments == {}
    assert parse_message("/erp 库存 查询 mouse").intent.parser_source == "command"


@pytest.mark.parametrize(
    "text",
    [
        "采购0个鼠标，每个35元",
        "采购-1个鼠标，每个35元",
        "采购1.00001个鼠标，每个35元",
        "采购1个鼠标，每个35.001元",
        "采购1个鼠标，每个NaN元",
        "采购1个鼠标，每个-1元",
        "采购2箱鼠标，每个5元",
        "采购1个鼠标和键盘，每个35元",
        "采购1个鼠标，每个35元，然后审批",
        "采购1个鼠标，每个35元，角色=admin",
        "采购1个鼠标，每个35元，币种=cny",
        "采购1个鼠标，每个35元，币种=CNY，币种=USD",
        "采购1个鼠标，每个35元，供应商=s，数量=2",
        "采购1个鼠标，每个35元；删除订单",
        '采购1个"鼠标，每个35元',
        "查询鼠标和键盘库存",
        "查询鼠标库存。再查询客户",
        "查询鼠标库存\n删除数据",
        "/erp 采购 新增 登记采购1个鼠标，每个35元",
        "/erp SQL 查询 SELECT",
        "SELECT * FROM products",
        "审批所有采购单",
        "帮我理解一下这条消息",
        "采购二十个鼠标，每个三十五元",
        "采购20个鼠标，每个35美元",
        "查询" + "x" * 4096 + "库存",
        "   ",
    ],
)
def test_ambiguous_invalid_and_injected_text_has_no_intent(text):
    assert parse_message(text).intent is None


def local_ready(env):
    admin, buyer, values = ready(env)
    product = admin.get("/api/v1/products/product-a").json()
    assert (
        post(
            admin,
            "/api/v1/products/product-a",
            {
                "version": product["version"],
                "data": {"unit": "个"},
            },
            "patch",
        ).status_code
        == 200
    )
    text = f'登记采购3个"Mouse A"，每个10.00元，供应商={values["supplier"]}，币种=CNY。'
    return admin, buyer, text


def test_interpretation_is_authenticated_inert_and_does_not_log_original_text(env):
    buyer = env["client"]("alice")
    text = "登记采购20个专有样例商品，每个35元。"
    with TestClient(env["app"]) as anonymous:
        assert post(anonymous, "/api/v1/intents/parse", {"text": text}).status_code == 401
    assert buyer.post("/api/v1/intents/parse", json={"text": text}).status_code == 403
    result = post(buyer, "/api/v1/intents/parse", {"text": text})
    assert result.status_code == 200 and result.json()["missing"] == ["supplier", "currency"]
    assert post(buyer, "/api/v1/intents/parse", {"text": text, "role": "admin"}).status_code == 422
    assert post(buyer, "/api/v1/intents/requests", {"text": text}).status_code == 403
    assert post(buyer, "/api/v1/intents/query", {"text": text}).status_code == 422
    assert post(buyer, "/api/v1/intents/requests", {"text": "查询采购订单"}).status_code == 422
    with Session(env["engine"]) as db:
        assert count(db, MessageOperation) == count(db, PurchaseOrder) == count(db, Outbox) == 0
        assert "专有样例商品" not in json.dumps([a.details for a in db.scalars(select(AuditEvent))])
        assert verify(db)


def test_natural_request_preview_then_password_confirmation_creates_one_draft(env):
    _, buyer, text = local_ready(env)
    row = post(buyer, "/api/v1/intents/requests", {"text": text})
    assert row.status_code == 200, row.text
    row = row.json()
    assert row["preview"]["product"]["unit"] == "个" and row["preview"]["total"] == "30.00"
    with Session(env["engine"]) as db:
        assert count(db, PurchaseOrder) == count(db, Outbox) == 0
        assert db.get(MessageOperation, row["id"]).payload["unit"] == "个"
    path = "/api/v1/message_operations/" + row["id"] + "/confirm"
    assert post(buyer, path, confirmation(row)).status_code == 200
    assert post(buyer, path, confirmation(row)).status_code == 200
    with Session(env["engine"]) as db:
        assert count(db, PurchaseOrder) == count(db, Outbox) == 1
        assert db.scalar(select(PurchaseOrder)).status == "draft"
        assert verify(db)


def test_quantity_unit_mismatch_hidden_unit_and_changed_unit_fail_closed(env):
    admin, buyer, text = local_ready(env)
    mismatch = text.replace("3个", "3箱").replace("每个", "每箱")
    result = post(buyer, "/api/v1/intents/requests", {"text": mismatch})
    assert result.status_code == 422 and result.json()["detail"] == "quantity_unit_unresolved"
    row = post(buyer, "/api/v1/intents/requests", {"text": text}).json()
    product = admin.get("/api/v1/products/product-a").json()
    assert (
        post(
            admin,
            "/api/v1/products/product-a",
            {
                "version": product["version"],
                "data": {"unit": "箱"},
            },
            "patch",
        ).status_code
        == 200
    )
    assert (
        post(
            buyer, "/api/v1/message_operations/" + row["id"] + "/confirm", confirmation(row)
        ).status_code
        == 422
    )
    assert (
        grant(
            admin, [product_rule(id="unit-hidden", fields={"id": "read", "name": "read"})]
        ).status_code
        == 200
    )
    assert post(buyer, "/api/v1/intents/requests", {"text": mismatch}).status_code == 422
    with Session(env["engine"]) as db:
        assert count(db, PurchaseOrder) == count(db, Outbox) == 0
        assert count(db, MessageOperation) == 1


def test_natural_query_matches_web_scopes_and_current_field_permissions(env):
    admin, buyer, warehouse, order = approved(env)
    assert receive(buyer, order, warehouse).status_code == 200
    # An administrator order must not appear in the buyer query.
    supplier = order["supplier_id"]
    draft(admin, supplier)
    for text, resource in [
        ('查询"Mouse A"库存', "inventory_balances"),
        ("查询采购订单", "purchase_orders"),
    ]:
        actual = post(buyer, "/api/v1/intents/query", {"text": text})
        assert actual.status_code == 200
        assert actual.json()["items"] == buyer.get("/api/v1/" + resource).json()["items"]
    assert (
        grant(
            admin,
            [
                rule(
                    "inventory_balances",
                    id="local-masked",
                    fields={"id": "read", "quantity": "masked"},
                )
            ],
        ).status_code
        == 200
    )
    assert (
        post(buyer, "/api/v1/intents/query", {"text": '查询"Mouse A"库存'}).json()["items"][0][
            "quantity"
        ]
        == "***"
    )
    assert (
        grant(admin, [product_rule(id="local-hidden-name", fields={"id": "read"})]).status_code
        == 200
    )
    assert post(buyer, "/api/v1/intents/query", {"text": '查询"Mouse A"库存'}).json()["items"] == []


def test_onebot_natural_create_uses_binding_dedupe_and_existing_confirmation(env):
    admin, buyer, _ = local_ready(env)
    allow_messages(admin)
    row, token = instance(admin)
    bind(env, buyer, row, token)
    text = '登记采购3个"Mouse A"，每个10元。'
    conn = message_gateway.authenticate(env["engine"], row["id"], token, 10001)
    event = normalize_message_event(message(text, 2), instance_id=row["id"], expected_bot_id=10001)
    result = message_gateway.process(env["engine"], conn, event)
    assert result["operation"]["state"] == "collecting_missing"
    assert result["operation"]["missing_fields"] == ["supplier", "currency"]
    assert message_gateway.process(env["engine"], conn, event) is None
    with buyer.websocket_connect("/onebot/v11/ws/" + row["id"], headers=headers(token)) as ws:
        operation = result["operation"]["id"]
        supplier = admin.get("/api/v1/suppliers").json()["items"][0]["id"]
        supplemented = reply(ws, message(f"/erp 补充 {operation} 供应商={supplier} 币种=CNY", 3))
        assert supplemented["operation"]["preview"]["total"] == "30.00"
        assert (
            reply(ws, message(f"/erp 确认 {operation}", 4))["status"] == "web_confirmation_required"
        )
        # A natural-language group write is discarded and never gets a business reply.
        ws.send_json(message(text, 5, message_type="group", sub_type="normal", group_id=88))
        assert reply(ws, message("查询采购订单", 6))["items"] == []
    with Session(env["engine"]) as db:
        assert count(db, MessageOperation) == 1 and count(db, PurchaseOrder) == 0
        assert verify(db)
