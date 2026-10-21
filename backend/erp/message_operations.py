"""Persistent previews; only explicit password-confirmed Web calls execute a purchase draft."""

import json
import shlex
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import func, or_, select

from . import procurement
from .audit import append, change_summary, digest
from .business_schemas import OrderInput
from .message_models import MessageBinding, MessageOperation, OneBotInstance
from .message_service import utc
from .models import now, uid
from .onebot.intent import parse_fixed_command
from .permissions import LEVEL, RESOURCES
from .services import data_for, require

PENDING = {"collecting_missing", "awaiting_confirmation"}
KEYS = {
    "product": "商品",
    "supplier": "供应商",
    "quantity": "数量",
    "unit_price": "单价",
    "currency": "币种",
}


def normalize(values):
    if not isinstance(values, dict) or not set(values) <= KEYS.keys():
        raise HTTPException(422, "invalid_operation_values")
    if any(not isinstance(v, str) or not v.strip() or len(v) > 160 for v in values.values()):
        raise HTTPException(422, "invalid_operation_values")
    values = {k: v.strip() for k, v in values.items()}
    if "currency" in values and (
        not values["currency"].isascii() or not values["currency"].isupper()
    ):
        raise HTTPException(422, "invalid_operation_values")
    parsed = parse_fixed_command(
        shlex.join(["/erp", "采购", "新增", *[KEYS[k] + "=" + v for k, v in values.items()]])
    )
    if parsed.intent is None:
        raise HTTPException(422, "invalid_operation_values")
    return values, list(parsed.missing)


def metadata(row):
    return {
        "id": row.id,
        "version": row.version,
        "owner_id": row.owner_id,
        "binding_id": row.binding_id,
        "resource": row.resource,
        "state": row.state,
        "result_id": row.result_id,
        "created_at": utc(row.created_at).isoformat(),
        "expires_at": utc(row.expires_at).isoformat(),
    }


def audit(db, row, action, previous=None):
    append(
        db,
        row.owner_id,
        uid(),
        "message_operation." + action,
        200,
        {
            "operation_id": row.id,
            "before_version": previous,
            "after_version": row.version,
            "state": row.state,
            "preview_digest": row.preview_digest,
        },
    )


def expire_owned(db, owner_id):
    for row in db.scalars(
        select(MessageOperation).where(
            MessageOperation.owner_id == owner_id,
            MessageOperation.state.in_(PENDING),
            MessageOperation.expires_at <= now(),
        )
    ):
        previous = row.version
        row.state, row.version = "expired", row.version + 1
        audit(db, row, "expired", previous)
    db.flush()


def binding_valid(db, engine, row):
    if row.binding_id is None:
        return
    binding = db.get(MessageBinding, row.binding_id)
    instance = db.get(OneBotInstance, binding.instance_id) if binding else None
    if (
        binding is None
        or not binding.active
        or binding.owner_id != engine.who.id
        or binding.version != row.binding_version
        or instance is None
        or not instance.active
    ):
        raise HTTPException(403, "operation_binding_invalid")
    require(engine.authorize("message_bindings", "use", data_for(db, "message_bindings", binding)))


def resolve(db, engine, resource, value):
    spec = RESOURCES[resource]
    model = spec.model
    options = [engine.readable_scope(resource, {"id"}) & (model.id == value)]
    for field in ("name", "sku" if resource == "products" else "code"):
        options.append(
            engine.readable_scope(resource, {"id", field}) & (getattr(model, field) == value)
        )
    rows = db.scalars(select(model).where(model.active.is_(True), or_(*options)).limit(2)).all()
    if len(rows) != 1:
        raise HTTPException(422, "reference_unresolved_or_ambiguous")
    return rows[0]


def prepare(db, engine, row):
    binding_valid(db, engine, row)
    values, missing = normalize(row.payload)
    if missing:
        return None, missing
    product = resolve(db, engine, "products", values["product"])
    supplier = resolve(db, engine, "suppliers", values["supplier"])
    body = OrderInput.model_validate(
        {
            "supplier_id": supplier.id,
            "currency": values["currency"],
            "lines": [
                {
                    "product_id": product.id,
                    "quantity": values["quantity"],
                    "unit_price": values["unit_price"],
                }
            ],
        }
    )
    _, candidate, lines = procurement.prepare_draft(db, engine, body, new_id=row.target_order_id)
    # A confirmation preview must expose every value the user is confirming, including all cost fields.
    decision = engine.authorize("purchase_orders", "read", candidate)
    require(decision)
    needed = {
        "id",
        "number",
        "supplier_id",
        "currency",
        "total",
        "lines",
        "unit_price",
        "line_amount",
    }
    if any(LEVEL[decision["fields"].get(f, "hidden")] < LEVEL["read"] for f in needed):
        raise HTTPException(403, "preview_read_denied")
    line = lines[0]
    refs = {"product": [product.id, product.version], "supplier": [supplier.id, supplier.version]}
    canonical = procurement.wire(
        {
            "candidate": candidate,
            "refs": refs,
            "quantity": line.quantity,
            "unit_price": line.unit_price,
            "binding_id": row.binding_id,
            "binding_version": row.binding_version,
        }
    )
    fingerprint = digest(json.dumps(canonical, sort_keys=True, separators=(",", ":")))
    preview = {
        "number": candidate["number"],
        "currency": body.currency,
        "total": format(candidate["total"], ".2f"),
        "quantity": format(line.quantity, "f"),
        "unit_price": format(line.unit_price, ".2f"),
    }
    for key, resource, ref in (
        ("product", "products", product),
        ("supplier", "suppliers", supplier),
    ):
        visible = engine.project(resource, data_for(db, resource, ref)) or {}
        preview[key] = {k: visible[k] for k in ("id", "name", "sku", "code") if k in visible}
    return {"body": body, "digest": fingerprint, "preview": preview}, []


def load(db, engine, record_id, action="read"):
    expire_owned(db, engine.who.id)
    row = db.scalar(
        select(MessageOperation).where(
            MessageOperation.id == record_id,
            MessageOperation.owner_id == engine.who.id,
            engine.scope("message_operations", action),
        )
    )
    if row is None:
        raise HTTPException(404, "record_not_found")
    return row


def project_metadata(engine, row):
    result = engine.project("message_operations", metadata(row)) or {}
    result.pop("result_id", None)
    return result


def result_view(db, engine, row):
    order = db.scalar(
        procurement.scoped_statement(engine, "purchase_orders").where(
            procurement.PurchaseOrder.id == row.result_id
        )
    )
    if order is None:
        return None
    return procurement.project(db, engine, "purchase_orders", order)


def view(db, engine, row, refresh=True):
    data = metadata(row)
    decision = engine.authorize("message_operations", "read", data)
    require(decision)
    result = project_metadata(engine, row)
    can_preview = LEVEL[decision["fields"].get("preview", "hidden")] >= LEVEL["read"]
    if row.state in PENDING and can_preview:
        plan, missing = prepare(db, engine, row)
        if plan:
            if refresh and plan["digest"] != row.preview_digest:
                previous = row.version
                row.preview_digest, row.version = plan["digest"], row.version + 1
                audit(db, row, "preview_refreshed", previous)
                db.flush()
                decision = engine.authorize("message_operations", "read", metadata(row))
                require(decision)
                if LEVEL[decision["fields"].get("preview", "hidden")] < LEVEL["read"]:
                    raise HTTPException(403, "preview_read_denied")
                result = project_metadata(engine, row)
            result["preview"] = plan["preview"]
            # A changed plan never gets an old confirmation digest, even when refresh is disabled.
            result["preview_digest"] = (
                plan["digest"] if row.preview_digest == plan["digest"] else None
            )
        if LEVEL[decision["fields"].get("missing_fields", "hidden")] >= LEVEL["read"]:
            result["missing_fields"] = missing
    if row.state == "completed":
        visible = result_view(db, engine, row)
        if visible:
            if LEVEL[decision["fields"].get("result", "hidden")] >= LEVEL["read"]:
                result["result"] = visible
            if (
                visible.get("id") == row.result_id
                and LEVEL[decision["fields"].get("result_id", "hidden")] >= LEVEL["read"]
            ):
                result["result_id"] = row.result_id
    return result


def create(db, engine, values, binding=None):
    expire_owned(db, engine.who.id)
    count = db.scalar(
        select(func.count())
        .select_from(MessageOperation)
        .where(MessageOperation.owner_id == engine.who.id, MessageOperation.state.in_(PENDING))
    )
    if count >= 20:
        raise HTTPException(429, "too_many_pending_operations")
    values, missing = normalize(values)
    row = MessageOperation(
        id=uid(),
        owner_id=engine.who.id,
        binding_id=binding.id if binding else None,
        binding_version=binding.version if binding else None,
        resource="purchase_orders",
        payload=values,
        target_order_id=uid(),
        state="collecting_missing" if missing else "awaiting_confirmation",
        version=1,
        expires_at=now() + timedelta(minutes=10),
        created_at=now(),
        updated_at=now(),
    )
    require(engine.authorize("message_operations", "create", metadata(row)), {"preview"})
    plan, _ = prepare(db, engine, row)
    row.preview_digest = plan["digest"] if plan else None
    db.add(row)
    db.flush()
    audit(db, row, "created")
    return row


def update(db, engine, row, values, version):
    if row.version != version:
        raise HTTPException(409, "version_conflict")
    if row.state not in PENDING or utc(row.expires_at) <= now():
        raise HTTPException(409, "operation_terminal")
    require(engine.authorize("message_operations", "update", metadata(row)), {"preview"})
    binding_valid(db, engine, row)
    values, missing = normalize({**row.payload, **values})
    old = row.version
    candidate = {
        **metadata(row),
        "version": old + 1,
        "state": "collecting_missing" if missing else "awaiting_confirmation",
    }
    require(engine.authorize("message_operations", "update", candidate), {"preview"})
    with db.no_autoflush:
        row.payload, row.state, row.version = values, candidate["state"], old + 1
        plan, _ = prepare(db, engine, row)
        row.preview_digest = plan["digest"] if plan else None
    audit(db, row, "updated", old)
    db.flush()
    return row


def cancel(db, engine, row, version):
    if row.version != version:
        raise HTTPException(409, "version_conflict")
    require(engine.authorize("message_operations", "cancel", metadata(row)), {"state"})
    if row.state not in PENDING or utc(row.expires_at) <= now():
        raise HTTPException(409, "operation_terminal")
    candidate = {**metadata(row), "version": row.version + 1, "state": "cancelled"}
    require(engine.authorize("message_operations", "cancel", candidate), {"state"})
    old = row.version
    row.state, row.version = "cancelled", row.version + 1
    audit(db, row, "cancelled", old)
    db.flush()
    return row


def confirm(db, engine, row, version, fingerprint):
    binding_valid(db, engine, row)
    require(engine.authorize("message_operations", "confirm", metadata(row)), {"state"})
    require(engine.authorize("message_operations", "read", metadata(row)))
    if row.state == "completed":
        if row.confirmed_version != version or fingerprint != row.preview_digest:
            raise HTTPException(409, "version_conflict")
        order = db.get(procurement.PurchaseOrder, row.result_id)
        require(
            engine.authorize("purchase_orders", "create", procurement.order_data(db, order)),
            {"supplier_id", "currency", "note", "lines", "unit_price"},
        )
        return row
    if row.version != version:
        raise HTTPException(409, "version_conflict")
    if row.state != "awaiting_confirmation" or utc(row.expires_at) <= now():
        raise HTTPException(409, "operation_terminal")
    decision = engine.authorize("message_operations", "read", metadata(row))
    if LEVEL[decision["fields"].get("preview", "hidden")] < LEVEL["read"]:
        raise HTTPException(403, "preview_read_denied")
    plan, missing = prepare(db, engine, row)
    if missing or fingerprint != row.preview_digest or fingerprint != plan["digest"]:
        raise HTTPException(409, "preview_stale")
    require(
        engine.authorize(
            "message_operations",
            "confirm",
            {
                **metadata(row),
                "state": "completed",
                "version": row.version + 1,
                "result_id": row.target_order_id,
            },
        ),
        {"state"},
    )
    order = procurement.draft(db, engine, plan["body"], new_id=row.target_order_id)
    final_plan, _ = prepare(db, engine, row)
    if final_plan["digest"] != fingerprint:
        raise HTTPException(409, "preview_stale")
    row.state, row.result_id, row.confirmed_version = "completed", order.id, version
    row.version += 1
    append(
        db,
        engine.who.id,
        uid(),
        "purchase.draft_from_operation",
        200,
        change_summary(
            "purchase_orders",
            order.id,
            None,
            procurement.order_data(db, order),
            {"supplier_id", "currency", "note", "lines"},
        ),
    )
    audit(db, row, "confirmed", version)
    db.flush()
    return row
