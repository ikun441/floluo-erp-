from fastapi import HTTPException
from pwdlib import PasswordHash
from pydantic import ValidationError
from sqlalchemy import delete, select

from .audit import change_summary
from .business_models import Category
from .business_schemas import CategoryInput, ClassifiedProductInput, SupplierInput, WarehouseInput
from .models import Department, Position, Role, SessionToken, User, UserRole
from .permissions import RESOURCES, Engine
from .schemas import DepartmentInput, NameInput, UserInput

PASSWORDS = PasswordHash.recommended()
INPUTS = {
    "products": ClassifiedProductInput,
    "categories": CategoryInput,
    "suppliers": SupplierInput,
    "customers": SupplierInput,
    "warehouses": WarehouseInput,
    "users": UserInput,
    "departments": DepartmentInput,
    "roles": NameInput,
    "positions": NameInput,
}


def data_for(db, resource, row):
    data = {
        key: getattr(row, key)
        for key in RESOURCES[resource].fields
        if key not in RESOURCES[resource].virtual_fields | {"password", "role_ids"}
    }
    if resource == "users":
        data["role_ids"] = list(
            db.scalars(select(UserRole.role_id).where(UserRole.user_id == row.id))
        )
    return data


def require(decision, fields=()):
    if not decision["allowed"]:
        raise HTTPException(403, decision["reason"])
    if decision["requires_approval"]:
        raise HTTPException(403, "approval_required")
    if any(decision["fields"].get(f) != "write" for f in fields):
        raise HTTPException(403, "field_write_denied")


def fetch(db, engine, resource, record_id, action="read"):
    res = RESOURCES[resource]
    row = db.scalar(
        select(res.model).where(res.model.id == record_id, engine.scope(resource, action))
    )
    if row is None:
        raise HTTPException(404, "record_not_found")
    return row


def validate_values(resource, values):
    try:
        return INPUTS[resource].model_validate(values).model_dump()
    except ValidationError as exc:
        # Validation messages can contain input values; never echo passwords.
        raise HTTPException(
            422, [{"field": ".".join(map(str, e["loc"])), "type": e["type"]} for e in exc.errors()]
        ) from None


def references(db, engine, resource, values, row_id, check_roles=True):
    for key, model in {
        "department_id": Department,
        "owner_id": User,
        "position_id": Position,
        "supervisor_id": User,
        "parent_id": Category if resource == "categories" else Department,
        "category_id": Category,
    }.items():
        if key == "category_id" or (key == "parent_id" and resource == "categories"):
            continue
        if values.get(key) and db.get(model, values[key]) is None:
            raise HTTPException(422, "invalid_reference")
    for key, target in (("category_id", "categories"), ("parent_id", "categories")):
        if values.get(key) and (key == "category_id" or resource == "categories"):
            row = fetch(db, engine, target, values[key])
            visible = engine.project(target, data_for(db, target, row))
            if not visible or visible.get("id") != row.id:
                raise HTTPException(404, "record_not_found")
    if resource == "users":
        roles = values.get("role_ids", [])
        if len(roles) != len(set(roles)):
            raise HTTPException(422, "duplicate_role")
        for role_id in roles if check_roles else []:
            role = db.get(Role, role_id)
            if role is None:
                raise HTTPException(422, "invalid_role")
            require(engine.authorize("roles", "assign", data_for(db, "roles", role)))
        parent, cls, attr = values.get("supervisor_id"), User, "supervisor_id"
    elif resource in {"departments", "categories"}:
        parent, cls, attr = (
            values.get("parent_id"),
            (Category if resource == "categories" else Department),
            "parent_id",
        )
    else:
        return
    seen = {row_id}
    while parent:
        if parent in seen:
            raise HTTPException(422, "relationship_cycle")
        seen.add(parent)
        record = db.get(cls, parent)
        parent = getattr(record, attr) if record else None


def project_record(db, engine, resource, row):
    result = engine.project(resource, data_for(db, resource, row))
    if result is None:
        return None
    # Relationship IDs are protected data too; never expose a hidden related record.
    key = (
        "category_id"
        if resource == "products"
        else "parent_id"
        if resource == "categories"
        else None
    )
    if key and result.get(key) and result[key] != "***":
        target = db.get(Category, result[key])
        visible = (
            engine.project("categories", data_for(db, "categories", target)) if target else None
        )
        if not visible or visible.get("id") != target.id:
            result.pop(key, None)
    return result


def persist(
    db, engine: Engine, resource, values, existing=None, changed_fields=None, audit_details=None
):
    from .models import uid

    before = data_for(db, resource, existing) if existing else None
    checked_fields = values.keys() if changed_fields is None else changed_fields
    row_id = existing.id if existing else uid()
    action = "update" if existing else "create"
    candidate = {**values, "id": row_id, "version": existing.version + 1 if existing else 1}
    if existing:
        require(
            engine.authorize(resource, action, data_for(db, resource, existing)), checked_fields
        )
    require(engine.authorize(resource, action, candidate), checked_fields)
    references(db, engine, resource, values, row_id, not existing or "role_ids" in checked_fields)
    attributes = {k: v for k, v in values.items() if k not in {"password", "role_ids"}}
    if resource == "users":
        if "password" in values:
            attributes["password_hash"] = PASSWORDS.hash(values["password"])
        if existing and ("password" in values or not values.get("active", existing.active)):
            for token in db.scalars(select(SessionToken).where(SessionToken.user_id == row_id)):
                token.revoked = True
    if existing:
        for k, v in attributes.items():
            setattr(existing, k, v)
        existing.version += 1
        row = existing
    else:
        row = RESOURCES[resource].model(id=row_id, **attributes)
        db.add(row)
    db.flush()
    if (
        resource == "users"
        and "role_ids" in values
        and (not existing or "role_ids" in checked_fields)
    ):
        db.execute(delete(UserRole).where(UserRole.user_id == row_id))
        for role_id in values["role_ids"]:
            db.add(UserRole(user_id=row_id, role_id=role_id))
    db.flush()
    if audit_details is not None:
        audit_details.update(
            change_summary(resource, row.id, before, data_for(db, resource, row), checked_fields)
        )
    # A write-only actor receives no protected record fields in the acknowledgement.
    return project_record(db, engine, resource, row) or {"saved": True}
