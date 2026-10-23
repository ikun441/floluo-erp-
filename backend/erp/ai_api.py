"""Short authorization transactions surround external I/O; no Gate lock during model calls."""

from contextlib import contextmanager

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import ai_service as service
from .ai_client import ModelFailure, infer
from .ai_models import AIConfiguration, AIRequest
from .ai_schemas import ConfigurationUpdate, ParseInput, RequestVersion
from .audit import change_summary
from .permissions import Engine, subject
from .services import require


def register(app, database, authenticated, authorized_engine, settings):
    app.state.ai_settings = settings
    managed = contextmanager(database)

    @contextmanager
    def phase(request, name):
        request.state.status = 200
        request.state.audit_details = {"component": "ai", "phase": name}
        with managed(request) as db:
            user = authenticated(request, db)
            engine = Engine(db, subject(db, user))
            yield db, engine, request.state.token

    @app.get("/api/v1/ai/configuration")
    def configuration(
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        data = service.configuration(db, settings)
        require(engine.authorize("ai_configuration", "read", data))
        return engine.project("ai_configuration", data)

    @app.patch("/api/v1/ai/configuration")
    def configure(
        request: Request,
        body: ConfigurationUpdate,
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        old = service.configuration(db, settings)
        fields = body.values.model_fields_set
        require(engine.authorize("ai_configuration", "update", old), fields)
        if body.version != old["version"]:
            raise HTTPException(409, "version_conflict")
        values = {key: old[key] for key in service.CONFIG_FIELDS}
        values.update(body.values.model_dump(exclude_unset=True))
        values = service.validate_configuration(values, settings)
        candidate = {**old, **values, "version": old["version"] + 1}
        require(engine.authorize("ai_configuration", "update", candidate), fields)
        row = db.get(AIConfiguration, 1)
        for key, value in values.items():
            setattr(row, key, value)
        row.version += 1
        request.state.audit_details = change_summary("ai_configuration", 1, old, candidate, fields)
        db.flush()
        return engine.project("ai_configuration", service.configuration(db, settings)) or {
            "saved": True
        }

    @app.get("/api/v1/ai/status")
    def status(
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        # No endpoint, model, credentials or internal configuration in the user-facing status.
        config = service.configuration(db, settings)
        return {"enabled": config["enabled"]}

    @app.get("/api/v1/ai/requests")
    def listing(
        request: Request,
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        rows = db.scalars(
            select(AIRequest)
            .where(
                AIRequest.owner_id == engine.who.id,
                AIRequest.session_digest == request.state.token.digest,
                engine.scope("ai_requests", "read"),
            )
            .order_by(AIRequest.created_at.desc(), AIRequest.id)
            .limit(20)
        )
        return {"items": [service.view(engine, row) for row in rows]}

    @app.get("/api/v1/ai/requests/{record_id}")
    def detail(
        record_id: str,
        request: Request,
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        row = service.owned_request(db, engine, request.state.token, record_id)
        return service.view(engine, row)

    @app.post("/api/v1/ai/requests")
    def parse(request: Request, body: ParseInput, idempotency_key: str = Header(default="")):
        with phase(request, "authorize") as (db, engine, token):
            record_id, config = service.start(db, engine, token, body, settings, idempotency_key)
            if config is None:
                return service.view(engine, service.owned_request(db, engine, token, record_id))
            original_session = token.digest
            request.state.audit_details["request_id"] = record_id
        # This call happens after commit and Session.close(), outside authorization_gate.
        intent, error = None, None
        try:
            intent = infer(config, body.text, settings)
        except ModelFailure as exc:
            error = exc.code
        with phase(request, "complete") as (db, engine, token):
            if token.digest != original_session:
                raise HTTPException(403, "ai_session_changed")
            result, code, error = service.finish(
                db, engine, token, record_id, intent, error, settings
            )
            request.state.status = code
            request.state.audit_details.update({"request_id": record_id, "error_code": error})
        if error:
            raise HTTPException(code, error)
        return result

    @app.post("/api/v1/ai/requests/{record_id}/execute")
    def execute(
        record_id: str,
        request: Request,
        body: RequestVersion,
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        row = service.owned_request(db, engine, request.state.token, record_id, "execute")
        result = service.execute(db, engine, request.state.token, row, body.version, settings)
        request.state.audit_details = {
            "component": "ai",
            "phase": "tool",
            "request_id": row.id,
            "tool": result["tool"],
            "policy_revision": engine.revision,
        }
        return result

    @app.post("/api/v1/ai/requests/{record_id}/cancel")
    def cancel(
        record_id: str,
        request: Request,
        body: RequestVersion,
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        row = service.owned_request(db, engine, request.state.token, record_id, "cancel")
        result = service.cancel(db, engine, row, body.version)
        request.state.audit_details = {"component": "ai", "phase": "cancel", "request_id": row.id}
        return result
