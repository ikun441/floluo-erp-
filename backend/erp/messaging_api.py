"""Web control plane for protocol instances and own platform bindings."""

from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import message_service as service
from .audit import change_summary, digest
from .message_models import MessageBinding, OneBotInstance
from .models import Throttle, User, now
from .permissions import Engine
from .services import PASSWORDS, data_for


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


PlatformId = Annotated[str, Field(pattern=r"^[1-9][0-9]{0,18}$")]


class InstanceInput(StrictInput):
    name: str = Field(min_length=1, max_length=120)
    bot_id: PlatformId

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value):
        if not value.strip():
            raise ValueError("blank name")
        return value.strip()

    @field_validator("bot_id")
    @classmethod
    def int64_id(cls, value):
        if int(value) > 2**63 - 1:
            raise ValueError("invalid id")
        return value


class Version(StrictInput):
    version: int = Field(ge=1)


class InstanceUpdate(Version):
    active: bool


class ChallengeInput(StrictInput):
    instance_id: str = Field(min_length=1, max_length=36)
    platform_user_id: PlatformId
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("platform_user_id")
    @classmethod
    def int64_id(cls, value):
        return InstanceInput.int64_id(value)


def register(app, database, authorized_engine):
    @app.get("/api/v1/onebot_instances")
    def instances(
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        rows = db.scalars(
            select(OneBotInstance)
            .where(engine.scope("onebot_instances", "read"))
            .order_by(OneBotInstance.id)
            .limit(100)
        )
        return {
            "items": [
                engine.project("onebot_instances", service.instance_data(db, row)) for row in rows
            ]
        }

    @app.post("/api/v1/onebot_instances")
    def create(
        request: Request,
        body: InstanceInput,
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        row, token = service.create_instance(db, engine, body.name, body.bot_id)
        request.state.audit_details = change_summary(
            "onebot_instances",
            row.id,
            None,
            service.instance_data(db, row),
            {"name", "bot_id", "active", "access_token"},
        )
        return {
            "instance": engine.project("onebot_instances", service.instance_data(db, row)),
            "access_token": token,
        }

    @app.patch("/api/v1/onebot_instances/{record_id}")
    def update(
        request: Request,
        record_id: str,
        body: InstanceUpdate,
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        row, _ = service.change_instance(db, engine, record_id, body.version, active=body.active)
        request.state.audit_details = {
            "resource": "onebot_instances",
            "record_id": row.id,
            "changed_fields": ["active"],
            "before_version": body.version,
            "after_version": row.version,
        }
        return engine.project("onebot_instances", service.instance_data(db, row)) or {"saved": True}

    @app.post("/api/v1/onebot_instances/{record_id}/rotate_token")
    def rotate(
        request: Request,
        record_id: str,
        body: Version,
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        row, token = service.change_instance(db, engine, record_id, body.version, rotate=True)
        request.state.audit_details = {
            "resource": "onebot_instances",
            "record_id": row.id,
            "changed_fields": ["access_token"],
            "before_version": body.version,
            "after_version": row.version,
        }
        return {
            "instance": engine.project("onebot_instances", service.instance_data(db, row)),
            "access_token": token,
        }

    @app.get("/api/v1/message_bindings")
    def bindings(
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        rows = db.scalars(
            select(MessageBinding)
            .where(
                MessageBinding.owner_id == engine.who.id, engine.scope("message_bindings", "read")
            )
            .order_by(MessageBinding.id)
            .limit(100)
        )
        return {
            "items": [
                engine.project("message_bindings", data_for(db, "message_bindings", row))
                for row in rows
            ]
        }

    @app.post("/api/v1/message_binding_challenges")
    def challenge(
        body: ChallengeInput,
        request: Request,
        response: Response,
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        user = db.get(User, engine.who.id)
        request.state.audit_details = {
            "instance_id": body.instance_id,
            "operation": "binding_challenge",
        }
        time = now()
        throttle = db.get(Throttle, digest("binding-challenge:" + user.id))
        if throttle is None:
            throttle = Throttle(
                key=digest("binding-challenge:" + user.id), failures=0, window_start=time
            )
            db.add(throttle)
        if service.utc(throttle.window_start) + timedelta(minutes=1) <= time:
            throttle.failures, throttle.window_start = 0, time
        if throttle.failures >= 5:
            response.status_code = request.state.status = 429
            return {"detail": "login_temporarily_unavailable"}
        throttle.failures += 1
        if user.locked_until and service.utc(user.locked_until) > now():
            response.status_code = request.state.status = 429
            return {"detail": "login_temporarily_unavailable"}
        if not PASSWORDS.verify(body.password, user.password_hash):
            user.failed_logins += 1
            if user.failed_logins >= 5:
                user.locked_until = now() + timedelta(minutes=15)
            response.status_code = request.state.status = 403
            return {"detail": "invalid_credentials"}
        result = service.issue_challenge(db, engine, body.instance_id, body.platform_user_id)
        user.failed_logins, user.locked_until = 0, None
        return result

    @app.post("/api/v1/message_bindings/{record_id}/revoke")
    def revoke(
        request: Request,
        record_id: str,
        body: Version,
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        result = service.revoke_binding(db, engine, record_id, body.version)
        request.state.audit_details = {
            "resource": "message_bindings",
            "record_id": record_id,
            "changed_fields": ["active"],
            "before_version": body.version,
            "after_version": body.version + 1,
        }
        return result
