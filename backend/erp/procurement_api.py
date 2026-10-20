from fastapi import Depends, Header, HTTPException, Query, Request
from sqlalchemy.orm import Session

from . import procurement as service
from .audit import change_summary
from .business_models import SystemConfiguration
from .business_schemas import ConfigurationUpdate, OrderInput, OrderUpdate, ReceiveInput, Transition
from .permissions import RESOURCES, Engine
from .services import require


def register(app, database, authorized_engine):
    def acknowledgement(db, engine, resource, row):
        visible = db.scalar(
            service.scoped_statement(engine, resource).where(RESOURCES[resource].model.id == row.id)
        )
        return service.project(db, engine, resource, visible) if visible else {"saved": True}

    def routes(resource):
        spec = RESOURCES[resource]

        def listing(
            limit: int = Query(50, ge=1, le=100),
            after: str | None = None,
            engine: Engine = Depends(authorized_engine),
            db: Session = Depends(database, scope="function"),
        ):
            statement = service.scoped_statement(engine, resource)
            if after:
                statement = statement.where(
                    engine.readable_scope(resource, {"id"}), spec.model.id > after
                )
            rows = db.scalars(statement.order_by(spec.model.id).limit(limit)).all()
            return {"items": [service.project(db, engine, resource, row) for row in rows]}

        def detail(
            record_id: str,
            engine: Engine = Depends(authorized_engine),
            db: Session = Depends(database, scope="function"),
        ):
            row = db.scalar(
                service.scoped_statement(engine, resource).where(spec.model.id == record_id)
            )
            if row is None:
                raise HTTPException(404, "record_not_found")
            return service.project(db, engine, resource, row)

        app.add_api_route("/api/v1/" + resource, listing, methods=["GET"])
        app.add_api_route("/api/v1/" + resource + "/{record_id}", detail, methods=["GET"])

    for resource in (
        "purchase_orders",
        "purchase_receipts",
        "inventory_balances",
        "stock_movements",
    ):
        routes(resource)

    @app.get("/api/v1/system_configuration")
    def configuration(
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        data = service.config_data(db)
        require(engine.authorize("system_configuration", "read", data))
        return engine.project("system_configuration", data)

    @app.patch("/api/v1/system_configuration")
    def configure(
        request: Request,
        body: ConfigurationUpdate,
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        old = service.config_data(db)
        require(
            engine.authorize("system_configuration", "update", old), body.values.model_fields_set
        )
        if old["version"] != body.version:
            raise HTTPException(409, "version_conflict")
        # Partial values preserve omitted settings; an omitted field cannot reset a protected value.
        new_values = {key: value for key, value in old.items() if key not in {"id", "version"}}
        new_values.update(body.values.model_dump(exclude_unset=True))
        candidate = {"id": 1, "version": old["version"] + 1, **new_values}
        require(
            engine.authorize("system_configuration", "update", candidate),
            body.values.model_fields_set,
        )
        row = db.get(SystemConfiguration, 1)
        row.values, row.version = new_values, candidate["version"]
        request.state.audit_details = change_summary(
            "system_configuration", 1, old, candidate, body.values.model_fields_set
        )
        db.flush()
        return engine.project("system_configuration", candidate) or {"saved": True}

    @app.post("/api/v1/purchase_orders")
    def create(
        request: Request,
        body: OrderInput,
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        row = service.draft(db, engine, body)
        request.state.audit_details = change_summary(
            "purchase_orders",
            row.id,
            None,
            service.order_data(db, row),
            {"supplier_id", "currency", "note", "lines"},
        )
        return acknowledgement(db, engine, "purchase_orders", row)

    @app.patch("/api/v1/purchase_orders/{record_id}")
    def update(
        request: Request,
        record_id: str,
        body: OrderUpdate,
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        row = service.locked_order(db, engine, record_id, "update")
        old = service.order_data(db, row)
        service.draft(db, engine, body, row)
        request.state.audit_details = change_summary(
            "purchase_orders",
            row.id,
            old,
            service.order_data(db, row),
            {"supplier_id", "currency", "note", "lines"},
        )
        return acknowledgement(db, engine, "purchase_orders", row)

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
                "purchase_orders",
                row.id,
                old,
                service.order_data(db, row),
                {"status", "approved_by"},
            )
            return acknowledgement(db, engine, "purchase_orders", row)

        app.add_api_route(
            "/api/v1/purchase_orders/{record_id}/" + action, execute, methods=["POST"]
        )

    for action in ("submit", "approve", "cancel"):
        transition_route(action)

    @app.post("/api/v1/purchase_orders/{record_id}/receive")
    def receive(
        request: Request,
        record_id: str,
        body: ReceiveInput,
        idempotency_key: str = Header(default=""),
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        row = service.locked_order(db, engine, record_id, "receive")
        old = service.order_data(db, row)
        receipt, replayed = service.receive(db, engine, row, body, idempotency_key)
        request.state.audit_details = change_summary(
            "purchase_orders",
            row.id,
            old,
            service.order_data(db, row),
            [] if replayed else {"status", "received_quantity"},
        )
        request.state.audit_details["replayed"] = replayed
        return acknowledgement(db, engine, "purchase_receipts", receipt)
