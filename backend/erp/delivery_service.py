"""Durable reply recipes. Retries only render authorized data, never repeat business commands."""

import json
from datetime import timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from . import message_gateway as gateway
from .audit import append
from .database import lock_gate
from .intent import BusinessIntent
from .local_parser import parse_message
from .message_models import MessageBinding, MessageDelivery
from .message_service import query_business, utc
from .models import User, now, uid
from .permissions import Engine, subject
from .services import data_for, require

PENDING = {"pending", "awaiting_ack"}
BACKOFF = (5, 15, 45)
STATIC = {
    "bound": {"status": "bound", "message": "账号已绑定，业务权限仍由ERP策略决定。"},
    "binding_required": {
        "status": "binding_required",
        "message": "请先在Web消息接入页面签发绑定码，并私聊兑换。",
    },
    "denied": {"status": "denied", "message": "操作被拒绝，请检查Web权限或重新签发绑定码。"},
    "unsupported_command": {
        "status": "unsupported_command",
        "message": "未识别为单条支持的指令，请改用 /erp 固定命令或Web表单；未调用AI。",
    },
    "web_required": {"status": "web_required", "message": "请在Web操作工作台查看当前请求。"},
}


def audit(db, row, event):
    append(
        db,
        row.owner_id,
        uid(),
        "onebot.delivery." + event,
        200,
        {
            "delivery_id": row.id,
            "instance_id": row.instance_id,
            "state": row.state,
            "attempts": row.attempts,
            "reason": row.last_error,
        },
    )


def finish(db, row, state, reason=None):
    row.state, row.last_error, row.recipe = state, reason, {}
    row.version += 1
    row.attempt_token = row.attempt_connection_id = None
    row.delivered_at = now() if state == "delivered" else None
    audit(db, row, state)


def recipe_for(event, reply, result):
    if result == "processed":
        parsed = parse_message(event.text)
        if parsed.intent and parsed.intent.operation == "query":
            return {
                "kind": "query",
                "resource": parsed.intent.resource,
                "arguments": parsed.intent.arguments,
            }
    if result == "operation":
        operation_id = reply.get("operation", {}).get("id")
        if isinstance(operation_id, str) and len(operation_id) == 36:
            return {
                "kind": "operation",
                "operation_id": operation_id,
                "confirmation": reply.get("status") == "web_confirmation_required",
            }
        return {"kind": "static", "code": "web_required"}
    code = reply.get("status")
    return {"kind": "static", "code": code if code in STATIC else "denied"}


def enqueue(db, event, actor_id, reply, result):
    if event.chat_type != "private":
        return
    binding = (
        db.scalar(
            select(MessageBinding).where(
                MessageBinding.instance_id == event.instance_id,
                MessageBinding.platform_user_id == str(event.user_id),
                MessageBinding.owner_id == actor_id,
                MessageBinding.active.is_(True),
            )
        )
        if actor_id
        else None
    )
    stamp = now()
    queued = db.scalar(
        select(func.count())
        .select_from(MessageDelivery)
        .where(
            MessageDelivery.instance_id == event.instance_id,
            MessageDelivery.state.in_(PENDING),
            MessageDelivery.expires_at > stamp,
        )
    )
    row = MessageDelivery(
        id=uid(),
        version=1,
        event_key=event.event_key,
        instance_id=event.instance_id,
        recipient_id=str(event.user_id),
        owner_id=actor_id,
        binding_id=binding.id if binding else None,
        binding_version=binding.version if binding else None,
        recipe=recipe_for(event, reply, result),
        state="pending",
        attempts=0,
        created_at=stamp,
        updated_at=stamp,
        next_attempt_at=stamp,
        expires_at=stamp + timedelta(minutes=5),
    )
    db.add(row)
    if queued >= 1000:
        finish(db, row, "failed", "queue_limit")
    else:
        audit(db, row, "queued")
    db.flush()


def bound_engine(db, row):
    binding = db.get(MessageBinding, row.binding_id) if row.binding_id else None
    user = db.get(User, row.owner_id) if row.owner_id else None
    if (
        binding is None
        or not binding.active
        or binding.version != row.binding_version
        or binding.instance_id != row.instance_id
        or binding.owner_id != row.owner_id
        or binding.platform_user_id != row.recipient_id
        or user is None
        or not user.active
        or (user.locked_until and utc(user.locked_until) > now())
    ):
        raise HTTPException(403, "delivery_identity_changed")
    engine = Engine(db, subject(db, user))
    require(engine.authorize("message_bindings", "use", data_for(db, "message_bindings", binding)))
    return engine


def render(db, row):
    recipe = row.recipe
    if not isinstance(recipe, dict):
        raise ValueError("invalid_recipe")
    if recipe.get("kind") == "static" and set(recipe) == {"kind", "code"}:
        code = recipe["code"]
        if not isinstance(code, str) or code not in STATIC:
            raise ValueError("invalid_recipe")
        if code == "bound":
            bound_engine(db, row)
        return dict(STATIC[code])
    engine = bound_engine(db, row)
    if recipe.get("kind") == "query" and set(recipe) == {"kind", "resource", "arguments"}:
        resource, arguments = recipe["resource"], recipe["arguments"]
        if (
            resource not in {"inventory", "purchase_orders"}
            or not isinstance(arguments, dict)
            or any(not isinstance(v, str) or not 1 <= len(v) <= 4096 for v in arguments.values())
            or (resource == "inventory" and set(arguments) != {"query"})
            or (resource == "purchase_orders" and not set(arguments) <= {"number"})
        ):
            raise ValueError("invalid_recipe")
        return query_business(db, engine, BusinessIntent("query", resource, arguments, {}, 1.0))
    if recipe.get("kind") == "operation" and set(recipe) == {
        "kind",
        "operation_id",
        "confirmation",
    }:
        from . import message_operations as operations

        if not isinstance(recipe["operation_id"], str) or type(recipe["confirmation"]) is not bool:
            raise ValueError("invalid_recipe")
        operation = operations.load(db, engine, recipe["operation_id"])
        if (
            operation.binding_id != row.binding_id
            or operation.binding_version != row.binding_version
        ):
            raise HTTPException(403, "delivery_identity_changed")
        return {
            "status": "web_confirmation_required" if recipe["confirmation"] else "operation",
            "operation": operations.view(db, engine, operation),
            "message": "在Web操作工作台预览并复核密码后才能创建采购草稿。",
        }
    raise ValueError("invalid_recipe")


def retry(db, row, reason):
    if row.attempts >= 3:
        finish(db, row, "failed", reason)
    else:
        row.state, row.last_error = "pending", reason
        row.next_attempt_at = now() + timedelta(seconds=BACKOFF[max(0, row.attempts - 1)])
        row.attempt_token = row.attempt_connection_id = None
        row.version += 1
        audit(db, row, "retry")


def claim(engine, connection):
    if not connection.connection_id:
        raise gateway.ConnectionRejected("delivery_requires_connection_lease")
    with Session(engine, expire_on_commit=False) as db:
        lock_gate(db)
        gateway.verify_connection(db, connection)
        stamp = now()
        rows = db.scalars(
            select(MessageDelivery)
            .where(
                MessageDelivery.instance_id == connection.instance_id,
                MessageDelivery.state.in_(PENDING),
                or_(
                    MessageDelivery.next_attempt_at <= stamp,
                    MessageDelivery.expires_at <= stamp,
                    (MessageDelivery.state == "awaiting_ack")
                    & (MessageDelivery.attempt_connection_id != connection.connection_id),
                ),
            )
            .order_by(MessageDelivery.created_at, MessageDelivery.id)
            .limit(20)
        ).all()
        for row in rows:
            if utc(row.expires_at) <= stamp:
                finish(db, row, "expired", "ttl_expired")
                continue
            if (
                row.state == "awaiting_ack"
                and row.attempt_connection_id == connection.connection_id
            ):
                retry(db, row, "ack_timeout")
                continue
            if row.attempts >= 3:
                finish(db, row, "failed", "attempt_limit")
                continue
            try:
                with db.begin_nested():
                    body = render(db, row)
            except HTTPException:
                finish(db, row, "suppressed", "authorization_changed")
                continue
            except (ValueError, TypeError, KeyError):
                finish(db, row, "suppressed", "invalid_recipe")
                continue
            text = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
            if len(text.encode("utf-8")) > 60000:
                text = json.dumps(
                    {"status": "web_required", "message": "结果较大，请通过Web查看。"},
                    ensure_ascii=False,
                )
            row.state, row.attempts, row.version = "awaiting_ack", row.attempts + 1, row.version + 1
            row.attempt_token, row.attempt_connection_id = uid(), connection.connection_id
            row.next_attempt_at = stamp + timedelta(seconds=15)
            row.last_error = None
            audit(db, row, "attempt")
            action = {
                "action": "send_private_msg",
                "params": {
                    "user_id": int(row.recipient_id),
                    "message": [{"type": "text", "data": {"text": text}}],
                },
                "echo": row.attempt_token,
            }
            db.commit()
            return action
        db.commit()
        return None


def ack_outcome(payload):
    status, code = payload.get("status"), payload.get("retcode")
    if type(code) is not int or not -(2**31) <= code < 2**31:
        raise ValueError("invalid_api_response")
    if status == "ok" and code == 0:
        return "delivered"
    if status == "async" and code == 1:
        return "wait"
    if status == "failed" and code not in {0, 1}:
        return "retry"
    raise ValueError("invalid_api_response")


def acknowledge(engine, connection, payload):
    outcome = ack_outcome(payload)
    token = payload.get("echo")
    try:
        if not isinstance(token, str) or str(UUID(token)) != token:
            return False
    except ValueError:
        return False
    with Session(engine) as db:
        lock_gate(db)
        gateway.verify_connection(db, connection)
        row = db.scalar(
            select(MessageDelivery).where(
                MessageDelivery.instance_id == connection.instance_id,
                MessageDelivery.attempt_token == token,
                MessageDelivery.attempt_connection_id == connection.connection_id,
                MessageDelivery.state == "awaiting_ack",
            )
        )
        if row is None:
            return False
        if utc(row.expires_at) <= now():
            finish(db, row, "expired", "ttl_expired")
        elif outcome == "delivered":
            finish(db, row, "delivered")
        elif outcome == "retry":
            retry(db, row, "api_failed")
        elif row.last_error != "async_unconfirmed":
            row.last_error, row.version = "async_unconfirmed", row.version + 1
            audit(db, row, "async_unconfirmed")
        db.commit()
        return True
