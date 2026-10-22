"""Procurement commands. Caller holds the authorization gate for the entire transaction."""

import json
from decimal import Decimal, localcontext

from fastapi import HTTPException
from sqlalchemy import and_, delete, exists, or_, select

from .audit import digest
from .business_models import (
    CommandExecution,
    InventoryBalance,
    PurchaseLine,
    PurchaseOrder,
    PurchaseReceipt,
    ReceiptLine,
    StockMovement,
)
from .models import Product, uid
from .order_support import (
    CENT,
    MAX_MONEY,
    MAX_QUANTITY,
    check_version,
    config_data,
    emit,
    reference,
    wire,
)
from .permissions import LEVEL, RESOURCES
from .services import data_for, require


def order_data(db, row):
    data = data_for(db, "purchase_orders", row)
    data["lines"] = [
        {
            "id": line.id,
            "product_id": line.product_id,
            "quantity": line.quantity,
            "received_quantity": line.received_quantity,
            "unit_price": line.unit_price,
            "amount": line.amount,
        }
        for line in db.scalars(
            select(PurchaseLine)
            .where(PurchaseLine.order_id == row.id)
            .order_by(PurchaseLine.line_number)
        )
    ]
    return data


def order_scope(engine, require_id=False):
    # Related scopes are inside SQL and applied before cursor/limit, including deny policies.
    product_ids = select(Product.id).where(engine.readable_scope("products", {"id"}))
    bad_line = exists(
        select(PurchaseLine.id).where(
            PurchaseLine.order_id == PurchaseOrder.id, PurchaseLine.product_id.not_in(product_ids)
        )
    )
    supplier = RESOURCES["suppliers"].model
    suppliers = select(supplier.id).where(engine.readable_scope("suppliers", {"id"}))
    own_scope = (
        engine.readable_scope("purchase_orders", {"id"})
        if require_id
        else engine.scope("purchase_orders", "read")
    )
    return own_scope & PurchaseOrder.supplier_id.in_(suppliers) & ~bad_line


def scoped_statement(engine, resource):
    model = RESOURCES[resource].model
    if resource == "purchase_orders":
        return select(model).where(order_scope(engine))
    warehouse = RESOURCES["warehouses"].model
    warehouses = select(warehouse.id).where(engine.readable_scope("warehouses", {"id"}))
    orders = select(PurchaseOrder.id).where(order_scope(engine, True))
    if resource == "purchase_receipts":
        return select(model).where(
            engine.scope(resource, "read"),
            model.warehouse_id.in_(warehouses),
            model.order_id.in_(orders),
        )
    products = select(Product.id).where(engine.readable_scope("products", {"id"}))
    statement = select(model).where(
        engine.scope(resource, "read"),
        model.warehouse_id.in_(warehouses),
        model.product_id.in_(products),
    )
    if resource == "stock_movements":
        receipts = select(PurchaseReceipt.id).where(
            engine.readable_scope("purchase_receipts", {"id"}),
            PurchaseReceipt.order_id.in_(orders),
            PurchaseReceipt.warehouse_id.in_(warehouses),
        )
        lines = select(ReceiptLine.id).where(ReceiptLine.receipt_id.in_(receipts))
        from .shipment import source_line_ids

        statement = statement.where(
            or_(
                and_(model.kind == "purchase_receipt", model.receipt_line_id.in_(lines)),
                and_(
                    model.kind == "sales_shipment",
                    model.shipment_line_id.in_(source_line_ids(engine)),
                ),
            )
        )
    return statement


def project(db, engine, resource, row):
    if resource == "purchase_orders":
        data = order_data(db, row)
        decision = engine.authorize(resource, "read", data)
        result = engine.project(resource, data)
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
        return wire(result)
    data = data_for(db, resource, row)
    if resource == "purchase_receipts":
        data["lines"] = [
            {
                "id": line.id,
                "purchase_line_id": line.purchase_line_id,
                "product_id": line.product_id,
                "quantity": line.quantity,
            }
            for line in db.scalars(
                select(ReceiptLine).where(ReceiptLine.receipt_id == row.id).order_by(ReceiptLine.id)
            )
        ]
    return wire(engine.project(resource, data))


def locked_order(db, engine, record_id, action):
    row = db.scalar(
        select(PurchaseOrder)
        .where(PurchaseOrder.id == record_id, engine.scope("purchase_orders", action))
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404, "record_not_found")
    reference(db, engine, "suppliers", row.supplier_id, active=action not in {"update", "cancel"})
    for line in db.scalars(
        select(PurchaseLine)
        .where(PurchaseLine.order_id == row.id)
        .order_by(PurchaseLine.id)
        .with_for_update()
    ):
        reference(
            db, engine, "products", line.product_id, active=action not in {"update", "cancel"}
        )
    return row


def prepare_draft(db, engine, body, existing=None, new_id=None):
    """Build and authorize a transient draft plan without persisting business records."""
    if existing:
        check_version(existing, body.version)
        if existing.status != "draft":
            raise HTTPException(409, "order_not_draft")
    reference(db, engine, "suppliers", body.supplier_id, active=True)
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
            PurchaseLine(
                id=uid(),
                line_number=i,
                product_id=line.product_id,
                quantity=line.quantity.quantize(Decimal("0.0001")),
                unit_price=line.unit_price.quantize(CENT),
                amount=amount,
                received_quantity=Decimal(0),
            )
        )
    if total > MAX_MONEY:
        raise HTTPException(422, "order_amount_overflow")
    row = existing or PurchaseOrder(
        id=new_id or uid(),
        number="PO-" + (new_id or uid()),
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
        "supplier_id": body.supplier_id,
        "currency": body.currency,
        "note": body.note,
        "total": total,
    }
    action = "update" if existing else "create"
    fields = {"supplier_id", "currency", "note", "lines", "unit_price"}
    if existing:
        require(engine.authorize("purchase_orders", action, order_data(db, row)), fields)
    require(engine.authorize("purchase_orders", action, values), fields)
    return row, values, lines


def draft(db, engine, body, existing=None, new_id=None):
    row, values, lines = prepare_draft(db, engine, body, existing, new_id)
    for key, value in values.items():
        setattr(row, key, value)
    db.add(row)
    db.flush()
    if existing:
        db.execute(delete(PurchaseLine).where(PurchaseLine.order_id == row.id))
    for line in lines:
        line.order_id = row.id
        db.add(line)
    db.flush()
    emit(db, row, "purchase.draft_saved")
    return row


def transition(db, engine, row, action, version):
    check_version(row, version)
    expected = {
        "submit": {"draft"},
        "approve": {"submitted"},
        "cancel": {"draft", "submitted", "approved"},
    }
    if row.status not in expected[action]:
        raise HTTPException(409, "invalid_order_transition")
    config = config_data(db)
    if action in {"submit", "approve"} and (
        row.currency not in config["supported_currencies"] or config["tax_mode"] != "no_tax"
    ):
        raise HTTPException(409, "business_rules_unconfigured")
    if (
        action == "approve"
        and config["require_separate_approver"]
        and row.owner_id == engine.who.id
    ):
        raise HTTPException(403, "self_approval_denied")
    old = order_data(db, row)
    new = {
        **old,
        "status": {"submit": "submitted", "approve": "approved", "cancel": "cancelled"}[action],
        "version": row.version + 1,
    }
    if action == "approve":
        new["approved_by"] = engine.who.id
    require(engine.authorize("purchase_orders", action, old))
    require(engine.authorize("purchase_orders", action, new))
    row.status, row.version, row.approved_by = new["status"], new["version"], new["approved_by"]
    emit(db, row, "purchase." + action)
    db.flush()
    return row


def receive(db, engine, row, body, key):
    if not key or len(key) > 128 or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise HTTPException(422, "invalid_idempotency_key")
    warehouse = reference(db, engine, "warehouses", body.warehouse_id, active=True)
    require(engine.authorize("warehouses", "receive", data_for(db, "warehouses", warehouse)))
    old = order_data(db, row)
    require(engine.authorize("purchase_orders", "receive", old))
    receipt_values = {
        "owner_id": engine.who.id,
        "department_id": engine.who.department_id,
        "warehouse_id": warehouse.id,
        "order_id": row.id,
    }
    command = {
        "operation": "purchase.receive",
        "order_id": row.id,
        "version": body.version,
        "warehouse_id": body.warehouse_id,
        "lines": sorted(
            [
                {
                    "line_id": line.line_id,
                    "quantity": format(line.quantity.quantize(Decimal("0.0001")), "f"),
                }
                for line in body.lines
            ],
            key=lambda x: x["line_id"],
        ),
    }
    fingerprint = digest(json.dumps(command, sort_keys=True, separators=(",", ":")))
    previous = db.scalar(
        select(CommandExecution).where(
            CommandExecution.subject_id == engine.who.id, CommandExecution.key == key
        )
    )
    if previous:
        if previous.payload_digest != fingerprint:
            raise HTTPException(409, "idempotency_payload_conflict")
        receipt = db.scalar(
            scoped_statement(engine, "purchase_receipts").where(
                PurchaseReceipt.id == previous.receipt_id
            )
        )
        if receipt is None:
            raise HTTPException(403, "receipt_read_denied")
        require(
            engine.authorize(
                "purchase_receipts", "create", data_for(db, "purchase_receipts", receipt)
            ),
            {"warehouse_id", "order_id", "lines"},
        )
        return receipt, True
    config = config_data(db)
    if row.currency not in config["supported_currencies"] or config["tax_mode"] != "no_tax":
        raise HTTPException(409, "business_rules_unconfigured")
    check_version(row, body.version)
    if row.status not in {"approved", "partially_received"}:
        raise HTTPException(409, "order_not_approved")
    lines = {
        line.id: line
        for line in db.scalars(
            select(PurchaseLine)
            .where(PurchaseLine.order_id == row.id)
            .order_by(PurchaseLine.id)
            .with_for_update()
        )
    }
    for item in body.lines:
        line = lines.get(item.line_id)
        if line is None or item.quantity > line.quantity - line.received_quantity:
            raise HTTPException(409, "invalid_or_excess_receipt_quantity")
    receipt = PurchaseReceipt(id=uid(), number="GR-" + uid(), **receipt_values)
    require(
        engine.authorize(
            "purchase_receipts",
            "create",
            {**receipt_values, "id": receipt.id, "number": receipt.number, "version": 1},
        ),
        {"warehouse_id", "order_id", "lines"},
    )
    db.add(receipt)
    db.flush()
    # Stable product order for balances, even with repeated products in different order lines.
    for item in sorted(body.lines, key=lambda item: (lines[item.line_id].product_id, item.line_id)):
        line = lines[item.line_id]
        received_line = ReceiptLine(
            id=uid(),
            receipt_id=receipt.id,
            purchase_line_id=line.id,
            product_id=line.product_id,
            quantity=item.quantity,
        )
        db.add(received_line)
        db.flush()
        balance = db.scalar(
            select(InventoryBalance)
            .where(
                InventoryBalance.warehouse_id == warehouse.id,
                InventoryBalance.product_id == line.product_id,
            )
            .with_for_update()
        )
        if balance is None:
            balance = InventoryBalance(
                warehouse_id=warehouse.id,
                product_id=line.product_id,
                owner_id=warehouse.owner_id,
                department_id=warehouse.department_id,
                quantity=Decimal(0),
                version=0,
            )
            db.add(balance)
        if balance.quantity + item.quantity > MAX_QUANTITY:
            raise HTTPException(409, "inventory_quantity_overflow")
        balance.quantity += item.quantity
        balance.version += 1
        db.add(
            StockMovement(
                receipt_line_id=received_line.id,
                warehouse_id=warehouse.id,
                product_id=line.product_id,
                owner_id=warehouse.owner_id,
                department_id=warehouse.department_id,
                quantity=item.quantity,
            )
        )
        line.received_quantity += item.quantity
        line.version += 1
        db.flush()
    new = {
        **old,
        "version": row.version + 1,
        "status": "received"
        if all(line.received_quantity == line.quantity for line in lines.values())
        else "partially_received",
    }
    require(engine.authorize("purchase_orders", "receive", new))
    row.status, row.version = new["status"], new["version"]
    db.add(
        CommandExecution(
            subject_id=engine.who.id, key=key, payload_digest=fingerprint, receipt_id=receipt.id
        )
    )
    emit(db, row, "purchase.received")
    db.flush()
    return receipt, False
