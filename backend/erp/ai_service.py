import json
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import func, select

from . import ai_gateway, message_operations
from .ai_client import ModelFailure, approved_endpoint
from .ai_models import AIConfiguration, AIHandoff, AIRequest
from .ai_schemas import CREATE_TOOL, TOOL_RESOURCES, AIIntent, ConfigurationValues
from .audit import digest
from .local_parser import parse_message
from .message_service import utc
from .models import now, uid
from .services import require

CONFIG_FIELDS = ("enabled", "base_url", "model", "timeout_seconds", "tools")


def configuration(db, settings):
    row = db.get(AIConfiguration, 1)
    return {
        "id": 1,
        "version": row.version,
        **{key: getattr(row, key) for key in CONFIG_FIELDS},
        "allowed_base_urls": list(settings.ai_allowed_base_urls),
        "credential_configured": bool(
            settings.ai_api_key and settings.ai_api_key.get_secret_value()
        ),
    }


def validate_configuration(values, settings):
    parsed = ConfigurationValues.model_validate(values)
    if parsed.base_url:
        try:
            approved_endpoint(parsed.base_url, settings.ai_allowed_base_urls)
        except ModelFailure:
            raise HTTPException(422, "ai_endpoint_denied") from None
    if parsed.enabled and (not parsed.base_url or not parsed.model or not parsed.tools):
        raise HTTPException(422, "ai_configuration_incomplete")
    return parsed.model_dump()


def request_data(row):
    return {
        "id": row.id,
        "version": row.version,
        "owner_id": row.owner_id,
        "config_version": row.config_version,
        "state": row.state,
        "intent": row.intent,
        "error_code": row.error_code,
        "created_at": utc(row.created_at).isoformat(),
        "expires_at": utc(row.expires_at).isoformat(),
    }


def preview_permission(engine, data, action="read"):
    decision = engine.authorize("ai_requests", action, data)
    require(decision)
    if any(
        decision["fields"].get(key) not in {"read", "write"}
        for key in ("id", "version", "state", "intent")
    ):
        raise HTTPException(403, "ai_preview_denied")


def view(engine, row):
    data = request_data(row)
    require(engine.authorize("ai_requests", "read", data))
    link = engine.db.get(AIHandoff, row.id)
    if link:
        from .message_models import MessageOperation

        operation = engine.db.get(MessageOperation, link.operation_id)
        decision = engine.authorize(
            "message_operations", "read", message_operations.metadata(operation)
        )
        if (
            decision["allowed"]
            and not decision["requires_approval"]
            and decision["fields"].get("id") in {"read", "write"}
        ):
            data["operation_id"] = link.operation_id
    return engine.project("ai_requests", data)


def owned_request(db, engine, token, record_id, action="read"):
    row = db.scalar(
        select(AIRequest)
        .where(
            AIRequest.id == record_id,
            AIRequest.owner_id == engine.who.id,
            AIRequest.session_digest == token.digest,
            engine.scope("ai_requests", action),
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404, "record_not_found")
    return row


def start(db, engine, token, body, settings, key):
    if (
        not key
        or len(key) > 128
        or not key.isascii()
        or any(ord(c) < 33 or ord(c) > 126 for c in key)
    ):
        raise HTTPException(422, "invalid_idempotency_key")
    config = configuration(db, settings)
    if not config["enabled"]:
        raise HTTPException(409, "ai_disabled")
    try:
        approved_endpoint(config["base_url"], settings.ai_allowed_base_urls)
    except ModelFailure:
        raise HTTPException(503, "ai_endpoint_denied") from None
    if parse_message(body.text).intent is not None:
        raise HTTPException(409, "ai_local_available")
    fingerprint = digest(
        json.dumps(
            {"text": body.text, "consent": body.consent, "config_version": config["version"]},
            sort_keys=True,
        )
    )
    existing = db.scalar(
        select(AIRequest).where(AIRequest.owner_id == engine.who.id, AIRequest.request_key == key)
    )
    if existing:
        if existing.session_digest != token.digest:
            raise HTTPException(404, "record_not_found")
        if existing.payload_digest != fingerprint:
            raise HTTPException(409, "idempotency_payload_conflict")
        require(engine.authorize("ai_requests", "create", request_data(existing)), {"intent"})
        preview_permission(engine, request_data(existing))
        if existing.state == "parsing":
            if utc(existing.lease_expires_at) > now():
                raise HTTPException(409, "ai_request_in_progress")
            existing.state, existing.intent = "failed", None
            existing.error_code, existing.version = "ai_parse_expired", existing.version + 1
            db.flush()
        return existing.id, None
    when = now()
    row = AIRequest(
        id=uid(),
        version=1,
        owner_id=engine.who.id,
        session_digest=token.digest,
        request_key=key,
        payload_digest=fingerprint,
        config_version=config["version"],
        state="parsing",
        intent=None,
        error_code=None,
        created_at=when,
        updated_at=when,
        expires_at=when + timedelta(minutes=5),
        lease_expires_at=when + timedelta(seconds=config["timeout_seconds"] + 10),
    )
    data = request_data(row)
    require(engine.authorize("ai_requests", "create", data), {"intent"})
    preview_permission(engine, data)
    active = (
        select(func.count())
        .select_from(AIRequest)
        .where(AIRequest.state == "parsing", AIRequest.lease_expires_at > when)
    )
    if (
        db.scalar(active) >= 2
        or db.scalar(active.where(AIRequest.owner_id == engine.who.id)) >= 1
        or db.scalar(
            select(func.count())
            .select_from(AIRequest)
            .where(
                AIRequest.owner_id == engine.who.id,
                AIRequest.created_at > when - timedelta(minutes=1),
            )
        )
        >= 5
    ):
        raise HTTPException(429, "ai_rate_limited")
    db.add(row)
    db.flush()
    return row.id, config


def finish(db, engine, token, record_id, intent, error_code, settings):
    row = owned_request(db, engine, token, record_id)
    if row.state != "parsing":
        raise HTTPException(409, "ai_request_cancelled")
    require(engine.authorize("ai_requests", "create", request_data(row)), {"intent"})
    config = configuration(db, settings)
    status = 502
    if utc(row.lease_expires_at) <= now() or utc(row.expires_at) <= now():
        error_code, status = "ai_parse_expired", 409
    elif not config["enabled"] or config["version"] != row.config_version:
        error_code, status = "ai_configuration_changed", 409
    else:
        try:
            approved_endpoint(config["base_url"], settings.ai_allowed_base_urls)
        except ModelFailure:
            error_code, status = "ai_endpoint_denied", 503
    if not error_code and tool_for(intent) not in config["tools"]:
        error_code, status = "ai_tool_disabled", 403
    row.version += 1
    if error_code:
        row.state, row.error_code, row.intent = "failed", error_code, None
        db.flush()
        return None, status, error_code
    row.state = intent_state(intent)
    row.intent = intent.model_dump()
    data = request_data(row)
    require(engine.authorize("ai_requests", "create", data), {"intent"})
    preview_permission(engine, data)
    db.flush()
    return view(engine, row), 200, None


def execute(db, engine, token, row, version, settings):
    if row.version != version:
        raise HTTPException(409, "version_conflict")
    preview_permission(engine, request_data(row))
    preview_permission(engine, request_data(row), "execute")
    if utc(row.expires_at) <= now():
        raise HTTPException(410, "ai_request_expired")
    if row.state != "ready":
        raise HTTPException(409, "ai_request_not_ready")
    config = configuration(db, settings)
    if not config["enabled"] or config["version"] != row.config_version:
        raise HTTPException(409, "ai_configuration_changed")
    intent = AIIntent.model_validate(row.intent)
    if intent.operation != "query":
        raise HTTPException(409, "ai_write_preview_required")
    return ai_gateway.execute(db, engine, intent, config["tools"])


def cancel(db, engine, row, version):
    if db.get(AIHandoff, row.id):
        raise HTTPException(409, "ai_request_transferred")
    if row.version != version:
        raise HTTPException(409, "version_conflict")
    if row.state not in {"parsing", "ready", "clarification"}:
        raise HTTPException(409, "ai_request_not_ready")
    require(engine.authorize("ai_requests", "cancel", request_data(row)), {"state"})
    row.state, row.intent, row.version = "cancelled", None, row.version + 1
    require(engine.authorize("ai_requests", "cancel", request_data(row)), {"state"})
    db.flush()
    return view(engine, row)


def tool_for(intent):
    return CREATE_TOOL if intent.operation == "create" else TOOL_RESOURCES[intent.resource][0]


def intent_state(intent):
    if intent.confidence < 0.8:
        return "clarification"
    if intent.operation == "create":
        _, missing = message_operations.normalize({**intent.arguments, **intent.references})
        if missing:
            return "clarification"
    return "ready"


def live_purchase(db, engine, row, version, settings, action):
    if row.version != version:
        raise HTTPException(409, "version_conflict")
    preview_permission(engine, request_data(row))
    preview_permission(engine, request_data(row), action)
    if utc(row.expires_at) <= now():
        raise HTTPException(410, "ai_request_expired")
    config = configuration(db, settings)
    if not config["enabled"] or config["version"] != row.config_version:
        raise HTTPException(409, "ai_configuration_changed")
    if row.state not in {"ready", "clarification"}:
        raise HTTPException(409, "ai_request_not_ready")
    intent = AIIntent.model_validate(row.intent)
    if intent.operation != "create" or tool_for(intent) not in config["tools"]:
        raise HTTPException(403, "ai_tool_disabled")
    if intent.confidence < 0.8:
        raise HTTPException(409, "ai_confidence_low")
    return intent


def supplement(db, engine, row, version, values, settings):
    intent = live_purchase(db, engine, row, version, settings, "update")
    if db.get(AIHandoff, row.id):
        raise HTTPException(409, "ai_request_transferred")
    if row.version >= 12:
        raise HTTPException(409, "ai_supplement_limit")
    merged, _ = message_operations.normalize({**intent.arguments, **intent.references, **values})
    updated = AIIntent.model_validate(
        {
            **intent.model_dump(),
            "arguments": {k: v for k, v in merged.items() if k not in {"product", "supplier"}},
            "references": {k: v for k, v in merged.items() if k in {"product", "supplier"}},
        }
    )
    candidate = {
        **request_data(row),
        "version": row.version + 1,
        "intent": updated.model_dump(),
        "state": intent_state(updated),
    }
    require(engine.authorize("ai_requests", "update", request_data(row)), {"intent"})
    require(engine.authorize("ai_requests", "update", candidate), {"intent"})
    preview_permission(engine, candidate)
    row.intent, row.state, row.version = (
        candidate["intent"],
        candidate["state"],
        candidate["version"],
    )
    db.flush()
    return view(engine, row)


def handoff(db, engine, row, version, settings):
    link = db.get(AIHandoff, row.id)
    # A retry must use the original accepted version, never silently accept changed parameters.
    if link and version != link.source_version:
        raise HTTPException(409, "version_conflict")
    intent = live_purchase(db, engine, row, row.version if link else version, settings, "prepare")
    if row.state != "ready":
        raise HTTPException(409, "ai_request_not_ready")
    bounded = ai_gateway.ToolEngine(engine, "purchase_orders", "create", "ai_prepare")
    if link:
        operation = message_operations.load(db, bounded, link.operation_id)
        message_operations.prepare(db, bounded, operation)
    else:
        operation = message_operations.create(
            db, bounded, {**intent.arguments, **intent.references}
        )
        link = AIHandoff(
            request_id=row.id, operation_id=operation.id, source_version=version, created_at=now()
        )
        db.add(link)
        row.version += 1
        candidate = request_data(row)
        require(engine.authorize("ai_requests", "prepare", candidate), {"intent"})
        preview_permission(engine, candidate)
        db.flush()
    metadata = message_operations.metadata(operation)
    decision = bounded.authorize("message_operations", "read", metadata)
    require(decision)
    if any(
        decision["fields"].get(key) not in {"read", "write"}
        for key in ("id", "version", "state", "preview")
    ):
        raise HTTPException(403, "preview_read_denied")
    # No order is created. From this explicit human transfer on, ordinary Web rules govern it.
    result = message_operations.view(db, bounded, operation)
    return {"request": view(engine, row), "operation": result}
