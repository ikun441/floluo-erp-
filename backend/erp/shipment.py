"""Authorized sales fulfillment. Caller holds the gate through the entire transaction."""

import json
from datetime import UTC
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select

from . import sales
from .audit import digest
from .business_models import InventoryBalance, StockMovement, Warehouse
from .models import uid
from .order_support import check_version, config_data, emit, reference, wire
from .sales_models import SalesLine, SalesOrder, SalesShipment, ShipmentExecution, ShipmentLine
from .services import data_for, require


def shipment_scope(engine, require_id=False):
    own = (
        engine.readable_scope("sales_shipments", {"id"})
        if require_id
        else engine.scope("sales_shipments", "read")
    )
    orders = select(SalesOrder.id).where(sales.order_scope(engine, True))
    warehouses = select(Warehouse.id).where(engine.readable_scope("warehouses", {"id"}))
    return own & SalesShipment.order_id.in_(orders) & SalesShipment.warehouse_id.in_(warehouses)


def source_line_ids(engine):
    shipments = select(SalesShipment.id).where(shipment_scope(engine, True))
    return select(ShipmentLine.id).where(ShipmentLine.shipment_id.in_(shipments))


def scoped_statement(engine):
    return select(SalesShipment).where(shipment_scope(engine))


def project(db, engine, row):
    data = data_for(db, "sales_shipments", row)
    data["lines"] = [
        {
            "id": line.id,
            "sales_line_id": line.sales_line_id,
            "product_id": line.product_id,
            "quantity": line.quantity,
        }
        for line in db.scalars(
            select(ShipmentLine).where(ShipmentLine.shipment_id == row.id).order_by(ShipmentLine.id)
        )
    ]
    created = row.created_at
    data["created_at"] = (
        created.replace(tzinfo=UTC) if created.tzinfo is None else created.astimezone(UTC)
    ).isoformat()
    return wire(engine.project("sales_shipments", data))


def ship(db, engine, row, body, key):
    if not key or len(key) > 128 or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise HTTPException(422, "invalid_idempotency_key")
    warehouse = reference(db, engine, "warehouses", body.warehouse_id)
    require(engine.authorize("warehouses", "ship", data_for(db, "warehouses", warehouse)))
    old = sales.order_data(db, row)
    require(engine.authorize("sales_orders", "ship", old))
    command = {
        "operation": "sales.ship",
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
            key=lambda item: item["line_id"],
        ),
    }
    fingerprint = digest(json.dumps(command, sort_keys=True, separators=(",", ":")))
    previous = db.scalar(
        select(ShipmentExecution).where(
            ShipmentExecution.subject_id == engine.who.id, ShipmentExecution.key == key
        )
    )
    if previous:
        if previous.payload_digest != fingerprint:
            raise HTTPException(409, "idempotency_payload_conflict")
        saved = db.scalar(scoped_statement(engine).where(SalesShipment.id == previous.shipment_id))
        if saved is None:
            raise HTTPException(403, "shipment_read_denied")
        require(
            engine.authorize("sales_shipments", "create", data_for(db, "sales_shipments", saved)),
            {"warehouse_id", "order_id", "lines"},
        )
        return saved, True
    check_version(row, body.version)
    if row.status not in {"approved", "partially_shipped"}:
        raise HTTPException(409, "sales_order_not_shippable")
    config = config_data(db)
    if row.currency not in config["supported_currencies"] or config["tax_mode"] != "no_tax":
        raise HTTPException(409, "business_rules_unconfigured")
    reference(db, engine, "warehouses", warehouse.id, active=True)
    reference(db, engine, "customers", row.customer_id, active=True)
    lines = {
        line.id: line
        for line in db.scalars(
            select(SalesLine)
            .where(SalesLine.order_id == row.id)
            .order_by(SalesLine.id)
            .with_for_update()
        )
    }
    demand = {}
    for item in body.lines:
        line = lines.get(item.line_id)
        if line is None or item.quantity > line.quantity - line.shipped_quantity:
            raise HTTPException(409, "invalid_or_excess_shipment_quantity")
        reference(db, engine, "products", line.product_id, active=True)
        demand[line.product_id] = demand.get(line.product_id, Decimal(0)) + item.quantity
    balances = {}
    for product_id in sorted(demand):
        balance = db.scalar(
            select(InventoryBalance)
            .where(
                InventoryBalance.warehouse_id == warehouse.id,
                InventoryBalance.product_id == product_id,
                engine.readable_scope("inventory_balances", {"id", "quantity"}),
            )
            .with_for_update()
        )
        if balance is None:
            raise HTTPException(404, "inventory_unavailable")
        if balance.quantity < demand[product_id]:
            raise HTTPException(409, "insufficient_stock")
        balances[product_id] = balance
    values = {
        "id": uid(),
        "version": 1,
        "number": "SH-" + uid(),
        "order_id": row.id,
        "warehouse_id": warehouse.id,
        "owner_id": engine.who.id,
        "department_id": engine.who.department_id,
    }
    require(
        engine.authorize("sales_shipments", "create", values), {"warehouse_id", "order_id", "lines"}
    )
    saved = SalesShipment(**values)
    db.add(saved)
    db.flush()
    for item in sorted(body.lines, key=lambda item: (lines[item.line_id].product_id, item.line_id)):
        line = lines[item.line_id]
        shipped = ShipmentLine(
            id=uid(),
            shipment_id=saved.id,
            sales_line_id=line.id,
            product_id=line.product_id,
            quantity=item.quantity,
        )
        db.add(shipped)
        db.flush()
        db.add(
            StockMovement(
                shipment_line_id=shipped.id,
                receipt_line_id=None,
                kind="sales_shipment",
                warehouse_id=warehouse.id,
                product_id=line.product_id,
                owner_id=warehouse.owner_id,
                department_id=warehouse.department_id,
                quantity=item.quantity,
            )
        )
        line.shipped_quantity += item.quantity
        line.version += 1
    for product_id, balance in balances.items():
        balance.quantity -= demand[product_id]
        balance.version += 1
    row.status = (
        "shipped"
        if all(line.shipped_quantity == line.quantity for line in lines.values())
        else "partially_shipped"
    )
    row.version += 1
    # Recheck the final state under the same locked policy revision before commit.
    db.flush()
    require(engine.authorize("sales_orders", "ship", sales.order_data(db, row)))
    db.add(
        ShipmentExecution(
            subject_id=engine.who.id, key=key, payload_digest=fingerprint, shipment_id=saved.id
        )
    )
    emit(db, row, "sales.shipped")
    db.flush()
    return saved, False
