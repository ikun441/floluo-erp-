"""Authenticated sales routes using the shared authorization transaction dependency."""

from typing import Literal

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import sales as service
from .audit import change_summary
from .business_schemas import SalesOrderInput, SalesOrderUpdate, Transition
from .permissions import Engine
from .sales_models import SalesOrder


def register(app, database, authorized_engine):
    def acknowledgement(db, engine, row):
        visible = db.scalar(
            select(SalesOrder).where(SalesOrder.id == row.id, service.order_scope(engine))
        )
        return service.project(db, engine, visible) if visible else {"saved": True}

    @app.get("/api/v1/sales_orders")
    def listing(
        limit: int = Query(50, ge=1, le=100),
        after: str | None = Query(None, max_length=36),
        status: Literal["draft", "submitted", "approved", "cancelled"] | None = None,
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        statement = select(SalesOrder).where(service.order_scope(engine))
        if status:
            statement = statement.where(
                engine.readable_scope("sales_orders", {"status"}), SalesOrder.status == status
            )
        if after:
            statement = statement.where(
                engine.readable_scope("sales_orders", {"id"}), SalesOrder.id > after
            )
        rows = db.scalars(statement.order_by(SalesOrder.id).limit(limit))
        return {"items": [service.project(db, engine, row) for row in rows]}

    @app.get("/api/v1/sales_orders/{record_id}")
    def detail(
        record_id: str,
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        row = db.scalar(
            select(SalesOrder).where(SalesOrder.id == record_id, service.order_scope(engine))
        )
        if row is None:
            raise HTTPException(404, "record_not_found")
        return service.project(db, engine, row)

    @app.post("/api/v1/sales_orders")
    def create(
        request: Request,
        body: SalesOrderInput,
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        row = service.draft(db, engine, body)
        request.state.audit_details = change_summary(
            "sales_orders",
            row.id,
            None,
            service.order_data(db, row),
            {"customer_id", "currency", "note", "lines"},
        )
        return acknowledgement(db, engine, row)

    @app.patch("/api/v1/sales_orders/{record_id}")
    def update(
        request: Request,
        record_id: str,
        body: SalesOrderUpdate,
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        row = service.locked_order(db, engine, record_id, "update")
        old = service.order_data(db, row)
        service.draft(db, engine, body, row)
        request.state.audit_details = change_summary(
            "sales_orders",
            row.id,
            old,
            service.order_data(db, row),
            {"customer_id", "currency", "note", "lines"},
        )
        return acknowledgement(db, engine, row)

    def transition_route(action):
        def execute(
            request: Request,
            record_id: str,
            body: Transition,
            engine: Engine = Depends(authorized_engine),
            db: Session = Depends(database, scope="function"),
        ):
            row = service.locked_order(db, engine, record_id, action)
            old = service.order_data(db, row)
            service.transition(db, engine, row, action, body.version)
            request.state.audit_details = change_summary(
                "sales_orders", row.id, old, service.order_data(db, row), {"status", "approved_by"}
            )
            return acknowledgement(db, engine, row)

        app.add_api_route("/api/v1/sales_orders/{record_id}/" + action, execute, methods=["POST"])

    for action in ("submit", "approve", "cancel"):
        transition_route(action)
