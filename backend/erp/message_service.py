"""Application services for message identity and read-only business tools.

Callers hold authorization_gate for the whole transaction. Protocol adapters never query DB.
"""

import secrets
from datetime import UTC, timedelta

from fastapi import HTTPException
from sqlalchemy import or_, select

from . import procurement
from .audit import digest
from .message_models import BindingChallenge, MessageBinding, OneBotInstance
from .models import Product, User, now, uid
from .onebot.intent import parse_fixed_command
from .permissions import Engine, subject
from .services import data_for, fetch, require


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def instance_data(db, row):
    return data_for(db, "onebot_instances", row)


def create_instance(db, engine, name, bot_id):
    token = secrets.token_urlsafe(32)
    row = OneBotInstance(
        id=uid(), version=1, name=name, bot_id=bot_id, active=True, token_digest=digest(token)
    )
    require(
        engine.authorize("onebot_instances", "create", instance_data(db, row)),
        {"name", "bot_id", "active", "access_token"},
    )
    db.add(row)
    db.flush()
    return row, token


def change_instance(db, engine, record_id, version, *, active=None, rotate=False):
    action = "rotate_token" if rotate else "update"
    row = fetch(db, engine, "onebot_instances", record_id, action)
    old = instance_data(db, row)
    fields = {"access_token"} if rotate else {"active"}
    require(engine.authorize("onebot_instances", action, old), fields)
    if row.version != version:
        raise HTTPException(409, "version_conflict")
    candidate = {**old, "version": row.version + 1}
    if not rotate:
        candidate["active"] = active
    require(engine.authorize("onebot_instances", action, candidate), fields)
    token = secrets.token_urlsafe(32) if rotate else None
    if rotate:
        row.token_digest = digest(token)
    else:
        row.active = active
    row.version += 1
    db.flush()
    return row, token


def binding_candidate(db, owner_id, instance_id, platform_id):
    rows = db.scalars(
        select(MessageBinding).where(
            MessageBinding.instance_id == instance_id,
            or_(
                MessageBinding.owner_id == owner_id, MessageBinding.platform_user_id == platform_id
            ),
        )
    ).all()
    for row in rows:
        if row.owner_id != owner_id or row.platform_user_id != platform_id or row.active:
            raise HTTPException(409, "binding_conflict")
    row = rows[0] if rows else None
    return row, {
        "id": row.id if row else uid(),
        "version": row.version + 1 if row else 1,
        "instance_id": instance_id,
        "platform_user_id": platform_id,
        "owner_id": owner_id,
        "active": True,
    }


def issue_challenge(db, engine, instance_id, platform_id):
    instance = fetch(db, engine, "onebot_instances", instance_id)
    projected = engine.project("onebot_instances", instance_data(db, instance))
    if not instance.active or not projected or projected.get("id") != instance.id:
        raise HTTPException(404, "record_not_found")
    _, candidate = binding_candidate(db, engine.who.id, instance_id, platform_id)
    require(
        engine.authorize("message_bindings", "create", candidate),
        {"instance_id", "platform_user_id", "owner_id", "active"},
    )
    # New challenges invalidate all older pending challenges for this owner/instance.
    for old in db.scalars(
        select(BindingChallenge).where(
            BindingChallenge.owner_id == engine.who.id,
            BindingChallenge.instance_id == instance_id,
            BindingChallenge.consumed.is_(False),
        )
    ):
        old.consumed = True
    code = secrets.token_urlsafe(24)
    expires = now() + timedelta(minutes=5)
    db.add(
        BindingChallenge(
            digest=digest(code),
            instance_id=instance_id,
            owner_id=engine.who.id,
            platform_user_id=platform_id,
            expires_at=expires,
            consumed=False,
        )
    )
    db.flush()
    return {"command": "/erp 绑定 " + code, "expires_at": expires.isoformat()}


def redeem_challenge(db, event, code):
    challenge = db.get(BindingChallenge, digest(code))
    if (
        challenge is None
        or challenge.consumed
        or utc(challenge.expires_at) <= now()
        or challenge.instance_id != event.instance_id
        or challenge.platform_user_id != str(event.user_id)
    ):
        raise HTTPException(403, "binding_challenge_invalid")
    user = db.get(User, challenge.owner_id)
    if user is None or not user.active or (user.locked_until and utc(user.locked_until) > now()):
        raise HTTPException(403, "binding_challenge_invalid")
    engine = Engine(db, subject(db, user))
    instance = fetch(db, engine, "onebot_instances", event.instance_id)
    visible = engine.project("onebot_instances", instance_data(db, instance))
    if not visible or visible.get("id") != event.instance_id:
        raise HTTPException(403, "binding_challenge_invalid")
    row, candidate = binding_candidate(db, user.id, event.instance_id, str(event.user_id))
    require(
        engine.authorize("message_bindings", "create", candidate),
        {"instance_id", "platform_user_id", "owner_id", "active"},
    )
    if row is None:
        row = MessageBinding(**candidate)
        db.add(row)
    else:
        row.active, row.version = True, candidate["version"]
    challenge.consumed = True
    db.flush()
    return user.id, {"status": "bound", "message": "账号已绑定，业务权限仍由ERP策略决定。"}


def revoke_binding(db, engine, record_id, version):
    row = db.get(MessageBinding, record_id)
    if row is None or row.owner_id != engine.who.id:
        raise HTTPException(404, "record_not_found")
    old = data_for(db, "message_bindings", row)
    require(engine.authorize("message_bindings", "revoke", old), {"active"})
    if row.version != version:
        raise HTTPException(409, "version_conflict")
    require(
        engine.authorize(
            "message_bindings", "revoke", {**old, "active": False, "version": row.version + 1}
        ),
        {"active"},
    )
    row.active, row.version = False, row.version + 1
    for challenge in db.scalars(
        select(BindingChallenge).where(
            BindingChallenge.owner_id == row.owner_id,
            BindingChallenge.instance_id == row.instance_id,
            BindingChallenge.consumed.is_(False),
        )
    ):
        challenge.consumed = True
    db.flush()
    return {"revoked": True}


def query_business(db, engine, intent):
    """Controlled tools: same SQL scopes/projection as Web, bounded before returning results."""
    if intent.operation != "query":
        return {"status": "web_required", "message": "消息写入尚未开放，请通过Web确认并操作。"}
    resource = "inventory_balances" if intent.resource == "inventory" else "purchase_orders"
    statement = procurement.scoped_statement(engine, resource)
    model = procurement.RESOURCES[resource].model
    if resource == "inventory_balances":
        products = select(Product.id).where(
            engine.readable_scope("products", {"id", "name"}),
            Product.name.contains(intent.arguments["query"], autoescape=True),
        )
        statement = statement.where(model.product_id.in_(products))
    elif intent.arguments.get("number"):
        statement = statement.where(
            engine.readable_scope(resource, {"number"}), model.number == intent.arguments["number"]
        )
    rows = db.scalars(statement.order_by(model.id).limit(20)).all()
    return {
        "resource": resource,
        "limit": 20,
        "items": [procurement.project(db, engine, resource, row) for row in rows],
    }


def dispatch(db, event):
    if event.chat_type != "private":
        return None, None, "group_blocked"
    prefix = "/erp 绑定 "
    if event.text.startswith(prefix):
        code = event.text[len(prefix) :].strip()
        if not code or len(code) > 128 or any(c.isspace() for c in code):
            raise HTTPException(403, "binding_challenge_invalid")
        actor, reply = redeem_challenge(db, event, code)
        return actor, reply, "bound"
    binding = db.scalar(
        select(MessageBinding).where(
            MessageBinding.instance_id == event.instance_id,
            MessageBinding.platform_user_id == str(event.user_id),
            MessageBinding.active.is_(True),
        )
    )
    if binding is None:
        return (
            None,
            {
                "status": "binding_required",
                "message": "请先在Web消息接入页面签发绑定码，并私聊兑换。",
            },
            "unbound",
        )
    user = db.get(User, binding.owner_id)
    if user is None or not user.active:
        raise HTTPException(403, "permission_denied")
    engine = Engine(db, subject(db, user))
    require(engine.authorize("message_bindings", "use", data_for(db, "message_bindings", binding)))
    parsed = parse_fixed_command(event.text)
    if parsed.intent is None:
        return user.id, {"status": "unsupported_command"}, "unsupported"
    if parsed.missing:
        return user.id, {"status": "missing_fields", "fields": list(parsed.missing)}, "incomplete"
    return user.id, query_business(db, engine, parsed.intent), "processed"


def bound_actor(db, event):
    return db.scalar(
        select(MessageBinding.owner_id).where(
            MessageBinding.instance_id == event.instance_id,
            MessageBinding.platform_user_id == str(event.user_id),
            MessageBinding.active.is_(True),
        )
    )
