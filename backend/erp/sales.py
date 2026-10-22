"""Sales application service. Caller holds the authorization gate until commit."""

from decimal import Decimal, localcontext

from fastapi import HTTPException
from sqlalchemy import delete, exists, select

from .models import Product, uid
from .order_support import CENT, MAX_MONEY, check_version, config_data, emit, reference, wire
from .permissions import LEVEL
from .sales_models import Customer, SalesLine, SalesOrder
from .services import data_for, require


def order_data(db, row):
    data = data_for(db, "sales_orders", row)
    data["lines"] = [
        {
            "id": line.id,
            "product_id": line.product_id,
            "quantity": line.quantity,
            "shipped_quantity": line.shipped_quantity,
            "unit_price": line.unit_price,
            "amount": line.amount,
        }
        for line in db.scalars(
            select(SalesLine).where(SalesLine.order_id == row.id).order_by(SalesLine.line_number)
        )
    ]
    return data


def order_scope(engine, require_id=False):
    products = select(Product.id).where(engine.readable_scope("products", {"id"}))
    customers = select(Customer.id).where(engine.readable_scope("customers", {"id"}))
    bad_line = exists(
        select(SalesLine.id).where(
            SalesLine.order_id == SalesOrder.id, SalesLine.product_id.not_in(products)
        )
    )
    own = (
        engine.readable_scope("sales_orders", {"id"})
        if require_id
        else engine.scope("sales_orders", "read")
    )
    return own & SalesOrder.customer_id.in_(customers) & ~bad_line


def project(db, engine, row):
    data = order_data(db, row)
    decision = engine.authorize("sales_orders", "read", data)
    result = engine.project("sales_orders", data)
    if result is None:
        return None
    mode = min(
        (decision["fields"].get(f, "hidden") for f in ("total", "unit_price", "line_amount")),
        key=LEVEL.get,
    )
    if mode == "hidden":
        result.pop("total", None)
    elif mode == "masked" and "total" in result:
        result["total"] = "***"
    if isinstance(result.get("lines"), list):
        for line in result["lines"]:
            if mode == "hidden":
                line.pop("unit_price", None)
                line.pop("amount", None)
            elif mode == "masked":
                line.update(unit_price="***", amount="***")
    if isinstance(result.get("lines"), list):
        shipped_mode = decision["fields"].get("shipped_quantity", "hidden")
        for line in result["lines"]:
            if shipped_mode == "hidden":
                line.pop("shipped_quantity", None)
            elif shipped_mode == "masked":
                line["shipped_quantity"] = "***"
    return wire(result)


def locked_order(db, engine, record_id, action):
    row = db.scalar(
        select(SalesOrder)
        .where(SalesOrder.id == record_id, engine.scope("sales_orders", action))
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404, "record_not_found")
    reference(
        db, engine, "customers", row.customer_id, active=action not in {"update", "cancel", "ship"}
    )
    for line in db.scalars(
        select(SalesLine)
        .where(SalesLine.order_id == row.id)
        .order_by(SalesLine.id)
        .with_for_update()
    ):
        reference(
            db,
            engine,
            "products",
            line.product_id,
            active=action not in {"update", "cancel", "ship"},
        )
    return row


def prepare_draft(db, engine, body, existing=None, new_id=None):
    """Build and authorize a transient draft plan without persisting business records."""
    if existing:
        check_version(existing, body.version)
        if existing.status != "draft":
            raise HTTPException(409, "order_not_draft")
    reference(db, engine, "customers", body.customer_id, active=True)
    lines, total = [], Decimal(0)
    for i, line in enumerate(body.lines, 1):
        reference(db, engine, "products", line.product_id, active=True)
        with localcontext() as arithmetic:
            arithmetic.prec = 64
            amount = line.quantity * line.unit_price
        if amount > MAX_MONEY or amount != amount.quantize(CENT):
            raise HTTPException(422, "line_amount_precision_or_overflow")
        amount = amount.quantize(CENT)
        total += amount
        lines.append(
            SalesLine(
                id=uid(),
                line_number=i,
                product_id=line.product_id,
                quantity=line.quantity.quantize(Decimal("0.0001")),
                unit_price=line.unit_price.quantize(CENT),
                amount=amount,
                shipped_quantity=Decimal(0),
            )
        )
    if total > MAX_MONEY:
        raise HTTPException(422, "order_amount_overflow")
    row = existing or SalesOrder(
        id=new_id or uid(),
        number="SO-" + (new_id or uid()),
        owner_id=engine.who.id,
        department_id=engine.who.department_id,
        status="draft",
        version=1,
    )
    values = {
        "id": row.id,
        "version": row.version + (1 if existing else 0),
        "number": row.number,
        "owner_id": row.owner_id,
        "department_id": row.department_id,
        "status": row.status,
        "approved_by": row.approved_by,
        "customer_id": body.customer_id,
        "currency": body.currency,
        "note": body.note,
        "total": total,
    }
    action = "update" if existing else "create"
    fields = {"customer_id", "currency", "note", "lines", "unit_price"}
    if existing:
        require(engine.authorize("sales_orders", action, order_data(db, row)), fields)
    require(engine.authorize("sales_orders", action, values), fields)
    return row, values, lines


def draft(db, engine, body, existing=None, new_id=None):
    row, values, lines = prepare_draft(db, engine, body, existing, new_id)
    for key, value in values.items():
        setattr(row, key, value)
    db.add(row)
    db.flush()
    if existing:
        db.execute(delete(SalesLine).where(SalesLine.order_id == row.id))
    for line in lines:
        line.order_id = row.id
        db.add(line)
    db.flush()
    emit(db, row, "sales.draft_saved")
    return row


def transition(db, engine, row, action, version):
    check_version(row, version)
    expected = {
        "submit": {"draft"},
        "approve": {"submitted"},
        "cancel": {"draft", "submitted", "approved"},
    }
    if action == "cancel" and any(
        line["shipped_quantity"] > 0 for line in order_data(db, row)["lines"]
    ):
        raise HTTPException(409, "shipped_order_cannot_cancel")
    if row.status not in expected[action]:
        raise HTTPException(409, "invalid_order_transition")
    config = config_data(db)
    if action in {"submit", "approve"} and (
        row.currency not in config["supported_currencies"] or config["tax_mode"] != "no_tax"
    ):
        raise HTTPException(409, "business_rules_unconfigured")
    if action == "approve" and row.owner_id == engine.who.id:
        raise HTTPException(403, "self_approval_denied")
    old = order_data(db, row)
    new = {
        **old,
        "status": {"submit": "submitted", "approve": "approved", "cancel": "cancelled"}[action],
        "version": row.version + 1,
    }
    if action == "approve":
        new["approved_by"] = engine.who.id
    require(engine.authorize("sales_orders", action, old))
    require(engine.authorize("sales_orders", action, new))
    row.status, row.version, row.approved_by = new["status"], new["version"], new["approved_by"]
    emit(db, row, "sales." + action)
    db.flush()
    return row
