"""Shared business helpers; callers hold the authorization gate transaction."""

from decimal import Decimal

from fastapi import HTTPException

from .business_models import Outbox, SystemConfiguration
from .business_schemas import ConfigurationValues
from .services import data_for, fetch

CENT = Decimal("0.01")
MAX_MONEY = Decimal("9999999999999999.99")
MAX_QUANTITY = Decimal("99999999999999.9999")


def wire(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {k: wire(v) for k, v in value.items()}
    if isinstance(value, list):
        return [wire(v) for v in value]
    return value


def config_data(db):
    row = db.get(SystemConfiguration, 1)
    if row is None:
        raise HTTPException(503, "configuration_missing")
    values = ConfigurationValues.model_validate(row.values).model_dump()
    return {"id": 1, "version": row.version, **values}


def reference(db, engine, resource, record_id, active=False):
    row = fetch(db, engine, resource, record_id)
    visible = engine.project(resource, data_for(db, resource, row))
    if not visible or visible.get("id") != row.id:
        raise HTTPException(404, "record_not_found")
    if active and not row.active:
        raise HTTPException(409, "inactive_reference")
    return row


def check_version(row, version):
    if row.version != version:
        raise HTTPException(409, "version_conflict")


def emit(db, row, event):
    # Outbox has no external data payload; a future consumer must reauthorize before fetching.
    db.add(Outbox(event_type=event, aggregate_id=row.id, payload={"version": row.version}))
