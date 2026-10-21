"""Read-only, scoped operational metadata; never expose reply recipes or credentials."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .delivery_service import PENDING, finish
from .message_models import OneBotInstance
from .message_service import utc
from .models import now
from .permissions import RESOURCES, Engine
from .services import data_for


def statement(engine, resource):
    model = RESOURCES[resource].model
    instances = select(OneBotInstance.id).where(engine.readable_scope("onebot_instances", {"id"}))
    return select(model).where(engine.scope(resource, "read"), model.instance_id.in_(instances))


def listing(db, engine, resource, state, after, limit):
    model = RESOURCES[resource].model
    if resource == "message_deliveries":
        # Expiry is server maintenance, scoped here to visible metadata; no business command runs.
        expired = db.scalars(
            statement(engine, resource)
            .where(
                model.state.in_(PENDING),
                model.expires_at <= now(),
            )
            .limit(100)
        ).all()
        for row in expired:
            finish(db, row, "expired", "ttl_expired")
        db.flush()
    query = statement(engine, resource)
    if state:
        query = query.where(engine.readable_scope(resource, {"state"}), model.state == state)
    if after:
        query = query.where(engine.readable_scope(resource, {"id"}), model.id > after)
    rows = db.scalars(query.order_by(model.id).limit(limit))
    projected = [engine.project(resource, data_for(db, resource, row)) for row in rows]
    # SQLite drops timezone information; normalize only after authorization and masking.
    return {
        "items": [
            {
                key: utc(value).astimezone(UTC).isoformat()
                if isinstance(value, datetime)
                else value
                for key, value in item.items()
            }
            for item in projected
            if item is not None
        ]
    }


def register(app, database, authorized_engine):
    @app.get("/api/v1/onebot_connections")
    def connections(
        state: Literal["connected", "disconnected"] | None = None,
        after: str | None = None,
        limit: int = Query(50, ge=1, le=100),
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        return listing(db, engine, "onebot_connections", state, after, limit)

    @app.get("/api/v1/message_deliveries")
    def deliveries(
        state: Literal["pending", "awaiting_ack", "delivered", "failed", "suppressed", "expired"]
        | None = None,
        after: str | None = None,
        limit: int = Query(50, ge=1, le=100),
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        return listing(db, engine, "message_deliveries", state, after, limit)
