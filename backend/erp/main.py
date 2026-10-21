import hmac
import logging
import secrets
from datetime import UTC, timedelta
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from . import __version__
from .audit import append, digest
from .config import Settings
from .database import lock_gate, make_engine
from .delivery_api import register as register_delivery
from .intent_api import register as register_intents
from .message_operations_api import register as register_message_operations
from .messaging_api import register as register_messaging
from .models import Gate, PolicyRevision, SessionToken, Throttle, User, now
from .onebot.transport import register as register_onebot
from .permissions import RESOURCES, Engine, conflicts, resource_catalog, subject, validate_rules
from .procurement_api import register as register_procurement
from .sales_api import register as register_sales
from .schemas import CreateEntity, Login, PatchEntity, Publish, Simulate
from .services import (
    INPUTS,
    PASSWORDS,
    data_for,
    fetch,
    persist,
    project_record,
    require,
    validate_values,
)

logger = logging.getLogger("erp")
DUMMY_HASH = PASSWORDS.hash(secrets.token_urlsafe(32))


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def create_app(settings=None):
    settings = settings or Settings()
    app = FastAPI(title="弗洛洛 ERP", version=__version__)
    app.state.engine = make_engine(settings.database_url)

    @app.middleware("http")
    async def trace(request, call_next):
        request.state.trace_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Trace-ID"] = request.state.trace_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {"field": ".".join(map(str, e["loc"])), "type": e["type"]} for e in exc.errors()
                ]
            },
        )

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        return JSONResponse(
            status_code=500,
            content={"detail": "internal_error"},
            headers={
                "X-Trace-ID": getattr(request.state, "trace_id", str(uuid4())),
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    def database(request: Request):
        with Session(app.state.engine, expire_on_commit=False) as db:
            try:
                lock_gate(db)
                yield db
                append(
                    db,
                    getattr(request.state, "actor", None),
                    request.state.trace_id,
                    request.method + " " + request.scope["route"].path,
                    getattr(request.state, "status", 200),
                    getattr(request.state, "audit_details", None),
                )
                db.commit()
            except HTTPException as exc:
                db.rollback()
                lock_gate(db)
                append(
                    db,
                    getattr(request.state, "actor", None),
                    request.state.trace_id,
                    request.method + " " + request.scope["route"].path,
                    exc.status_code,
                )
                db.commit()
                raise
            except RequestValidationError:
                db.rollback()
                lock_gate(db)
                append(
                    db,
                    getattr(request.state, "actor", None),
                    request.state.trace_id,
                    request.method + " " + request.scope["route"].path,
                    422,
                )
                db.commit()
                raise
            except IntegrityError:
                db.rollback()
                lock_gate(db)
                append(
                    db,
                    getattr(request.state, "actor", None),
                    request.state.trace_id,
                    request.method + " " + request.scope["route"].path,
                    409,
                )
                db.commit()
                raise HTTPException(409, "integrity_conflict") from None
            except Exception:
                db.rollback()
                try:
                    lock_gate(db)
                    append(
                        db,
                        getattr(request.state, "actor", None),
                        request.state.trace_id,
                        request.method + " " + request.scope["route"].path,
                        500,
                    )
                    db.commit()
                except Exception:
                    db.rollback()
                    logger.error(
                        "failure_audit_unavailable", extra={"trace_id": request.state.trace_id}
                    )
                logger.error("request_failed", extra={"trace_id": request.state.trace_id})
                raise

    def origin(request):
        if request.headers.get("origin") not in {None, settings.app_origin}:
            raise HTTPException(403, "origin_denied")

    def authenticated(request: Request, db: Session = Depends(database, scope="function")):
        raw = request.cookies.get("erp_session", "")
        token = db.get(SessionToken, digest(raw)) if raw else None
        if token is None or token.revoked or utc(token.expires_at) <= now():
            raise HTTPException(401, "authentication_required")
        user = db.get(User, token.user_id)
        if user is None or not user.active:
            raise HTTPException(401, "authentication_required")
        request.state.actor = user.id
        request.state.token = token
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin(request)
            header = request.headers.get("x-csrf-token", "")
            cookie = request.cookies.get("erp_csrf", "")
            if (
                not header
                or not hmac.compare_digest(header, cookie)
                or not hmac.compare_digest(digest(header), token.csrf_digest)
            ):
                raise HTTPException(403, "csrf_denied")
        return user

    def authorized_engine(
        db: Session = Depends(database, scope="function"), user: User = Depends(authenticated)
    ):
        return Engine(db, subject(db, user))

    @app.get("/health/live")
    def live():
        return {"status": "ok", "version": __version__}

    @app.get("/health/ready")
    def ready():
        try:
            with Session(app.state.engine) as db:
                db.execute(text("SELECT 1"))
                if db.get(Gate, 1) is None:
                    raise RuntimeError()
            return {"status": "ok"}
        except (SQLAlchemyError, RuntimeError):
            return JSONResponse(status_code=503, content={"status": "not_ready"})

    @app.post("/api/v1/auth/login")
    def login(
        body: Login,
        request: Request,
        response: Response,
        db: Session = Depends(database, scope="function"),
    ):
        origin(request)
        time = now()
        key = digest(request.client.host if request.client else "unknown")
        throttle = db.get(Throttle, key)
        if throttle is None:
            throttle = Throttle(key=key, failures=0, window_start=time)
            db.add(throttle)
        if utc(throttle.window_start) + timedelta(minutes=15) <= time:
            throttle.failures, throttle.window_start = 0, time
        user = db.scalar(select(User).where(User.username == body.username.lower()))
        locked = user and user.locked_until and utc(user.locked_until) > time
        valid = PASSWORDS.verify(body.password, user.password_hash if user else DUMMY_HASH)
        if throttle.failures >= 20 or locked:
            request.state.status = 429
            response.status_code = 429
            return {"detail": "login_temporarily_unavailable"}
        if not user or not user.active or not valid:
            throttle.failures += 1
            if user:
                user.failed_logins += 1
                if user.failed_logins >= 5:
                    user.locked_until = time + timedelta(minutes=15)
            request.state.status = 401
            response.status_code = 401
            return {"detail": "invalid_credentials"}
        user.failed_logins, user.locked_until = 0, None
        raw, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        old = request.cookies.get("erp_session")
        if old:
            prior = db.get(SessionToken, digest(old))
            if prior and prior.user_id == user.id:
                prior.revoked = True
        db.add(
            SessionToken(
                digest=digest(raw),
                csrf_digest=digest(csrf),
                user_id=user.id,
                expires_at=time + timedelta(minutes=settings.session_minutes),
            )
        )
        request.state.actor = user.id
        for name, value, httponly in [("erp_session", raw, True), ("erp_csrf", csrf, False)]:
            response.set_cookie(
                name,
                value,
                httponly=httponly,
                secure=settings.secure_cookies,
                samesite="strict",
                max_age=settings.session_minutes * 60,
                path="/",
            )
        return {"user_id": user.id}

    @app.get("/api/v1/auth/me")
    def me(user: User = Depends(authenticated)):
        return {"id": user.id, "username": user.username}

    @app.post("/api/v1/auth/logout")
    def logout(request: Request, response: Response, user: User = Depends(authenticated)):
        request.state.token.revoked = True
        response.delete_cookie("erp_session", path="/")
        response.delete_cookie("erp_csrf", path="/")
        return {"logged_out": True}

    @app.get("/api/v1/resource_catalog")
    def catalog(user: User = Depends(authenticated)):
        return resource_catalog()

    @app.get("/api/v1/policies")
    def policies(
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        gate = db.get(Gate, 1)
        rev = db.get(PolicyRevision, gate.revision_id) if gate.revision_id else None
        candidate = {
            "id": rev.id if rev else "",
            "number": engine.revision,
            "rules": rev.rules if rev else [],
        }
        require(engine.authorize("policies", "read", candidate))
        projected = engine.project("policies", candidate)
        return projected

    @app.post("/api/v1/policies/publish")
    def publish(
        body: Publish,
        user: User = Depends(authenticated),
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        gate = db.get(Gate, 1)
        current = db.get(PolicyRevision, gate.revision_id) if gate.revision_id else None
        require(
            engine.authorize(
                "policies",
                "publish",
                {
                    "id": current.id if current else "",
                    "number": engine.revision,
                    "rules": current.rules if current else [],
                },
            )
        )
        if engine.revision != body.expected_revision:
            raise HTTPException(409, "policy_revision_conflict")
        try:
            validate_rules(body.rules)
        except ValueError:
            raise HTTPException(422, "invalid_policy") from None
        # JSON policy references are checked before publication, not accepted as arbitrary IDs.
        from .models import Department, Role

        for rule in body.rules:
            cls = {"user": User, "role": Role, "department": Department}.get(rule.subject.kind)
            if cls and db.get(cls, rule.subject.id) is None:
                raise HTTPException(422, "invalid_policy_subject")
            scope_cls = (
                Department if rule.scope == "departments" else RESOURCES[rule.resource].model
            )
            if rule.scope in {"departments", "records"} and any(
                db.get(scope_cls, i) is None for i in rule.scope_ids
            ):
                raise HTTPException(422, "invalid_scope_reference")
        revision = PolicyRevision(
            number=engine.revision + 1,
            author_id=user.id,
            rules=[r.model_dump() for r in body.rules],
        )
        db.add(revision)
        db.flush()
        gate.revision_id = revision.id
        return {"revision": revision.number, "conflicts": conflicts(body.rules)}

    @app.post("/api/v1/policies/simulate")
    def simulate(
        body: Simulate,
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        gate = db.get(Gate, 1)
        require(
            engine.authorize(
                "policies", "simulate", {"id": gate.revision_id, "number": engine.revision}
            )
        )
        if body.resource not in RESOURCES or body.action not in RESOURCES[body.resource].actions:
            raise HTTPException(422, "unsupported_simulation")
        user = db.get(User, body.user_id)
        row = db.get(RESOURCES[body.resource].model, body.record_id)
        if user is None or row is None:
            raise HTTPException(404, "record_not_found")
        return Engine(db, subject(db, user)).authorize(
            body.resource, body.action, data_for(db, body.resource, row)
        )

    register_procurement(app, database, authorized_engine)
    register_sales(app, database, authorized_engine)
    register_messaging(app, database, authorized_engine)
    register_message_operations(app, database, authorized_engine)
    register_intents(app, database, authorized_engine)
    register_delivery(app, database, authorized_engine)
    register_onebot(app)

    # Explicit registry prevents arbitrary table access through the path parameter.
    def resource_spec(resource):
        if resource not in INPUTS:
            raise HTTPException(404, "unknown_resource")
        return RESOURCES[resource]

    @app.get("/api/v1/{resource}")
    def listing(
        resource: str,
        limit: int = Query(50, ge=1, le=100),
        after: str | None = None,
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        spec = resource_spec(resource)
        statement = select(spec.model).where(engine.scope(resource, "read"))
        if after:
            statement = statement.where(
                engine.readable_scope(resource, {"id"}), spec.model.id > after
            )
        rows = db.scalars(statement.order_by(spec.model.id).limit(limit)).all()
        return {"items": [project_record(db, engine, resource, row) for row in rows]}

    @app.get("/api/v1/{resource}/{record_id}")
    def detail(
        resource: str,
        record_id: str,
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        resource_spec(resource)
        row = fetch(db, engine, resource, record_id)
        return project_record(db, engine, resource, row)

    @app.post("/api/v1/{resource}")
    def create(
        request: Request,
        resource: str,
        body: CreateEntity,
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        resource_spec(resource)
        values = validate_values(resource, body.data)
        request.state.audit_details = {}
        return persist(db, engine, resource, values, audit_details=request.state.audit_details)

    @app.patch("/api/v1/{resource}/{record_id}")
    def update(
        request: Request,
        resource: str,
        record_id: str,
        body: PatchEntity,
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        resource_spec(resource)
        row = fetch(db, engine, resource, record_id, "update")
        if row.version != body.version:
            raise HTTPException(409, "version_conflict")
        old = data_for(db, resource, row)
        current = {k: v for k, v in old.items() if k not in {"id", "version"}}
        if resource == "users":
            # Existing passwords are never serialized or rehashed unless explicitly reset.
            schema = INPUTS[resource].model_fields
            if not set(body.data) <= set(schema):
                raise HTTPException(422, "unknown_field")
            partial = {**current, **body.data}
            validation = validate_values(
                resource,
                {**partial, "password": body.data.get("password", "validation-placeholder-only")},
            )
            if "password" not in body.data:
                validation.pop("password")
        else:
            validation = validate_values(resource, {**current, **body.data})
        # Check changed fields, but evaluate conditions against complete old/new candidates.
        changed = {k: v for k, v in validation.items() if k in body.data}
        from .services import references

        require(engine.authorize(resource, "update", old), changed.keys())
        require(engine.authorize(resource, "update", {**old, **validation}), changed.keys())
        references(db, engine, resource, validation, row.id, "role_ids" in changed)
        # persist rechecks every submitted field; restrict validation to actual patch keys.
        request.state.audit_details = {}
        return persist(
            db,
            engine,
            resource,
            {**current, **changed},
            row,
            changed.keys(),
            request.state.audit_details,
        )

    return app


app = create_app()
