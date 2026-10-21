"""Authenticated Web workbench for durable operation previews and explicit confirmation."""

from typing import Annotated, Literal

from fastapi import Depends, Query, Request, Response
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import message_operations as service
from . import reauthentication
from .message_models import MessageOperation
from .messaging_api import StrictInput, Version
from .models import User
from .permissions import Engine

Values = dict[str, Annotated[str, Field(min_length=1, max_length=160)]]


class CreateInput(StrictInput):
    values: Values = Field(default_factory=dict, max_length=5)


class UpdateInput(Version):
    values: Values = Field(max_length=5)


class ConfirmInput(Version):
    preview_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    password: str = Field(min_length=1, max_length=1024)


def register(app, database, authorized_engine):
    @app.get("/api/v1/message_operations")
    def listing(
        state: Literal[
            "collecting_missing", "awaiting_confirmation", "completed", "cancelled", "expired"
        ]
        | None = None,
        limit: int = Query(50, ge=1, le=100),
        after: str | None = None,
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        service.expire_owned(db, engine.who.id)
        statement = select(MessageOperation).where(
            MessageOperation.owner_id == engine.who.id, engine.scope("message_operations", "read")
        )
        if state:
            statement = statement.where(MessageOperation.state == state)
        if after:
            statement = statement.where(
                engine.readable_scope("message_operations", {"id"}), MessageOperation.id > after
            )
        rows = db.scalars(statement.order_by(MessageOperation.id).limit(limit)).all()
        return {"items": [service.project_metadata(engine, row) for row in rows]}

    @app.get("/api/v1/message_operations/{record_id}")
    def detail(
        record_id: str,
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        return service.view(db, engine, service.load(db, engine, record_id))

    @app.post("/api/v1/message_operations")
    def create(
        body: CreateInput,
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        return service.view(db, engine, service.create(db, engine, body.values))

    @app.patch("/api/v1/message_operations/{record_id}")
    def update(
        record_id: str,
        body: UpdateInput,
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        row = service.load(db, engine, record_id, "update")
        service.update(db, engine, row, body.values, body.version)
        return service.view(db, engine, row)

    @app.post("/api/v1/message_operations/{record_id}/cancel")
    def cancel(
        record_id: str,
        body: Version,
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        row = service.load(db, engine, record_id, "cancel")
        service.cancel(db, engine, row, body.version)
        return service.view(db, engine, row)

    @app.post("/api/v1/message_operations/{record_id}/confirm")
    def confirm(
        record_id: str,
        body: ConfirmInput,
        request: Request,
        response: Response,
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        row = service.load(db, engine, record_id, "confirm")
        request.state.audit_details = {"operation_id": row.id}
        status = reauthentication.verify(
            db, db.get(User, engine.who.id), body.password, "operation-confirm"
        )
        if status:
            response.status_code = request.state.status = status
            return {
                "detail": "login_temporarily_unavailable"
                if status == 429
                else "invalid_credentials"
            }
        service.confirm(db, engine, row, body.version, body.preview_digest)
        return service.view(db, engine, row)
