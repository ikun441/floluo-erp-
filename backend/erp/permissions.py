"""A small typed policy language compiled to bound SQL expressions, never evaluated code."""

import operator
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from sqlalchemy import and_, false, func, not_, or_, select, true
from sqlalchemy.orm import Session

from .business_models import (
    Category,
    InventoryBalance,
    PurchaseOrder,
    PurchaseReceipt,
    StockMovement,
    Supplier,
    SystemConfiguration,
    Warehouse,
)
from .message_models import (
    MessageBinding,
    MessageDelivery,
    MessageOperation,
    OneBotConnection,
    OneBotInstance,
)
from .models import Department, Gate, PolicyRevision, Position, Product, Role, User, UserRole
from .sales_models import Customer, SalesOrder
from .schemas import Rule


@dataclass(frozen=True)
class Resource:
    model: type
    fields: frozenset[str]
    actions: frozenset[str] = frozenset({"read", "create", "update"})
    owner_column: str | None = None
    department_column: str | None = None
    virtual_fields: frozenset[str] = frozenset()


RESOURCES = {
    "products": Resource(
        Product,
        frozenset(
            {
                "id",
                "version",
                "sku",
                "name",
                "unit",
                "owner_id",
                "department_id",
                "active",
                "category_id",
            }
        ),
        owner_column="owner_id",
        department_column="department_id",
    ),
    "users": Resource(
        User,
        frozenset(
            {
                "id",
                "version",
                "username",
                "department_id",
                "position_id",
                "supervisor_id",
                "active",
                "role_ids",
                "password",
            }
        ),
        owner_column="id",
        department_column="department_id",
    ),
    "departments": Resource(Department, frozenset({"id", "version", "name", "parent_id"})),
    "positions": Resource(Position, frozenset({"id", "version", "name"})),
    "roles": Resource(
        Role,
        frozenset({"id", "version", "name"}),
        frozenset({"read", "create", "update", "assign"}),
    ),
    "policies": Resource(
        PolicyRevision,
        frozenset({"id", "number", "rules"}),
        frozenset({"read", "publish", "simulate"}),
    ),
}
RESOURCES.update(
    {
        "categories": Resource(Category, frozenset({"id", "version", "name", "parent_id"})),
        "suppliers": Resource(
            Supplier,
            frozenset(
                {
                    "id",
                    "version",
                    "code",
                    "name",
                    "contact",
                    "phone",
                    "owner_id",
                    "department_id",
                    "active",
                }
            ),
            owner_column="owner_id",
            department_column="department_id",
        ),
        "warehouses": Resource(
            Warehouse,
            frozenset({"id", "version", "code", "name", "owner_id", "department_id", "active"}),
            owner_column="owner_id",
            department_column="department_id",
        ),
    }
)

RESOURCES.update(
    {
        "purchase_orders": Resource(
            PurchaseOrder,
            frozenset(
                {
                    "id",
                    "version",
                    "number",
                    "supplier_id",
                    "owner_id",
                    "department_id",
                    "currency",
                    "total",
                    "status",
                    "note",
                    "approved_by",
                    "lines",
                    "unit_price",
                    "line_amount",
                }
            ),
            frozenset({"read", "create", "update", "submit", "approve", "cancel", "receive"}),
            "owner_id",
            "department_id",
            frozenset({"lines", "unit_price", "line_amount"}),
        ),
        "purchase_receipts": Resource(
            PurchaseReceipt,
            frozenset(
                {
                    "id",
                    "version",
                    "number",
                    "order_id",
                    "warehouse_id",
                    "owner_id",
                    "department_id",
                    "lines",
                }
            ),
            frozenset({"read", "create"}),
            "owner_id",
            "department_id",
            frozenset({"lines"}),
        ),
        "inventory_balances": Resource(
            InventoryBalance,
            frozenset(
                {
                    "id",
                    "version",
                    "warehouse_id",
                    "product_id",
                    "quantity",
                    "owner_id",
                    "department_id",
                }
            ),
            frozenset({"read"}),
            "owner_id",
            "department_id",
        ),
        "stock_movements": Resource(
            StockMovement,
            frozenset(
                {
                    "id",
                    "version",
                    "warehouse_id",
                    "product_id",
                    "quantity",
                    "kind",
                    "receipt_line_id",
                    "owner_id",
                    "department_id",
                }
            ),
            frozenset({"read"}),
            "owner_id",
            "department_id",
        ),
        "system_configuration": Resource(
            SystemConfiguration,
            frozenset(
                {"id", "version", "supported_currencies", "tax_mode", "require_separate_approver"}
            ),
            frozenset({"read", "update"}),
            virtual_fields=frozenset(
                {"supported_currencies", "tax_mode", "require_separate_approver"}
            ),
        ),
    }
)
RESOURCES["warehouses"] = Resource(
    Warehouse,
    RESOURCES["warehouses"].fields,
    frozenset({"read", "create", "update", "receive"}),
    "owner_id",
    "department_id",
)


RESOURCES["customers"] = Resource(
    Customer,
    RESOURCES["suppliers"].fields,
    owner_column="owner_id",
    department_column="department_id",
)
RESOURCES["sales_orders"] = Resource(
    SalesOrder,
    (RESOURCES["purchase_orders"].fields - {"supplier_id"}) | {"customer_id"},
    frozenset({"read", "create", "update", "submit", "approve", "cancel"}),
    "owner_id",
    "department_id",
    frozenset({"lines", "unit_price", "line_amount"}),
)


RESOURCES.update(
    {
        "onebot_instances": Resource(
            OneBotInstance,
            frozenset({"id", "version", "name", "bot_id", "active", "access_token"}),
            frozenset({"read", "create", "update", "rotate_token"}),
            virtual_fields=frozenset({"access_token"}),
        ),
        "message_bindings": Resource(
            MessageBinding,
            frozenset({"id", "version", "instance_id", "platform_user_id", "owner_id", "active"}),
            frozenset({"read", "create", "revoke", "use"}),
            "owner_id",
        ),
    }
)


RESOURCES["message_operations"] = Resource(
    MessageOperation,
    frozenset(
        {
            "id",
            "version",
            "owner_id",
            "binding_id",
            "resource",
            "state",
            "result_id",
            "created_at",
            "expires_at",
            "preview",
            "missing_fields",
            "result",
        }
    ),
    frozenset({"read", "create", "update", "cancel", "confirm"}),
    "owner_id",
    virtual_fields=frozenset({"created_at", "expires_at", "preview", "missing_fields", "result"}),
)


def condition_value(column, value):
    if column.type.python_type is Decimal:
        if type(value) not in {str, int}:
            raise ValueError("decimal conditions require strings or integers")
        try:
            result = Decimal(value)
        except InvalidOperation:
            raise ValueError("invalid decimal condition") from None
        if not result.is_finite():
            raise ValueError("nonfinite decimal condition")
        return result
    if type(value) is not column.type.python_type:
        raise ValueError("condition value type does not match field")
    return value


def resource_catalog():
    return {
        name: {
            "fields": sorted(res.fields),
            "actions": sorted(res.actions),
            "scopes": ["all", "records"]
            + (["own"] if res.owner_column else [])
            + (["department", "departments"] if res.department_column else []),
        }
        for name, res in RESOURCES.items()
    }


RESOURCES["onebot_connections"] = Resource(
    OneBotConnection,
    frozenset(
        {
            "id",
            "version",
            "instance_id",
            "instance_version",
            "state",
            "connected_at",
            "last_seen_at",
            "lease_expires_at",
            "disconnected_at",
            "disconnect_reason",
        }
    ),
    frozenset({"read"}),
)
RESOURCES["message_deliveries"] = Resource(
    MessageDelivery,
    frozenset(
        {
            "id",
            "version",
            "instance_id",
            "owner_id",
            "state",
            "attempts",
            "next_attempt_at",
            "expires_at",
            "delivered_at",
            "last_error",
            "created_at",
            "updated_at",
        }
    ),
    frozenset({"read"}),
    "owner_id",
)


LEVEL = {"hidden": 0, "masked": 1, "read": 2, "write": 3}


@dataclass(frozen=True)
class Subject:
    id: str
    department_id: str | None
    roles: frozenset[str]
    active: bool


def subject(db: Session, user: User) -> Subject:
    roles = db.scalars(select(UserRole.role_id).where(UserRole.user_id == user.id)).all()
    return Subject(user.id, user.department_id, frozenset(roles), user.active)


def validate_rules(rules: list[Rule]):
    if len({r.id for r in rules}) != len(rules):
        raise ValueError("duplicate rule id")
    for rule in rules:
        resource = RESOURCES.get(rule.resource)
        if resource is None or not set(rule.actions) <= resource.actions:
            raise ValueError("unknown resource/action")
        if not set(rule.fields) <= resource.fields:
            raise ValueError("unknown field")
        if rule.scope == "own" and not resource.owner_column:
            raise ValueError("resource has no owner scope")
        if rule.scope in {"department", "departments"} and not resource.department_column:
            raise ValueError("resource has no department scope")
        if rule.scope in {"departments", "records"} and not rule.scope_ids:
            raise ValueError("explicit scope ids required")
        for c in rule.conditions:
            if c.field not in resource.fields or c.field in resource.virtual_fields | {
                "password",
                "role_ids",
                "rules",
            }:
                raise ValueError("unsupported condition field")
            column = getattr(resource.model, c.field)
            python_type = column.type.python_type
            values = c.value if isinstance(c.value, list) else [c.value]
            for value in values:
                condition_value(column, value)
            if python_type is bool and c.op not in {"eq", "in"}:
                raise ValueError("boolean ordering is not supported")
        if any(
            rule.fields.get(field, "hidden") in {"masked", "read"}
            for field in ("password", "access_token")
        ):
            raise ValueError("password is write-only")


def conflicts(rules: list[Rule]):
    return [
        {"allow": a.id, "deny": b.id, "reason": "potential overlap; explicit deny takes priority"}
        for a in rules
        if a.effect == "allow"
        for b in rules
        if b.effect == "deny" and a.resource == b.resource and set(a.actions) & set(b.actions)
    ]


class Engine:
    def __init__(self, db: Session, who: Subject):
        self.db, self.who = db, who
        gate = db.get(Gate, 1)
        rev = db.get(PolicyRevision, gate.revision_id) if gate and gate.revision_id else None
        self.revision = rev.number if rev else 0
        self.rules = [Rule.model_validate(r) for r in rev.rules] if rev else []
        validate_rules(self.rules)

    def applicable(self, resource, action):
        if (
            not self.who.active
            or resource not in RESOURCES
            or action not in RESOURCES[resource].actions
        ):
            return []

        def matches(s):
            return (
                s.kind == "all"
                or s.kind == "user"
                and s.id == self.who.id
                or s.kind == "role"
                and s.id in self.who.roles
                or s.kind == "department"
                and self.who.department_id is not None
                and s.id == self.who.department_id
            )

        return [
            r
            for r in self.rules
            if r.resource == resource and action in r.actions and matches(r.subject)
        ]

    def predicate(self, rule):
        res = RESOURCES[rule.resource]
        model = res.model
        scope = true()
        if rule.scope == "own":
            scope = getattr(model, res.owner_column) == self.who.id
        elif rule.scope == "department":
            scope = (
                false()
                if self.who.department_id is None
                else getattr(model, res.department_column) == self.who.department_id
            )
        elif rule.scope == "departments":
            scope = getattr(model, res.department_column).in_(rule.scope_ids)
        elif rule.scope == "records":
            scope = model.id.in_(rule.scope_ids)
        conditions = []
        for c in rule.conditions:
            column = getattr(model, c.field)
            if c.op == "in":
                conditions.append(column.in_([condition_value(column, v) for v in c.value]))
            else:
                operation = {
                    "eq": operator.eq,
                    "lt": operator.lt,
                    "lte": operator.le,
                    "gt": operator.gt,
                    "gte": operator.ge,
                }[c.op]
                conditions.append(operation(column, condition_value(column, c.value)))
        return func.coalesce(and_(scope, *conditions), false())

    def scope(self, resource, action):
        rules = self.applicable(resource, action)
        allows = [self.predicate(r) for r in rules if r.effect == "allow"]
        denies = [self.predicate(r) for r in rules if r.effect == "deny"]
        pending = (
            [self.predicate(r) for r in rules if r.effect == "allow" and r.requires_approval]
            if action == "read"
            else []
        )
        return and_(
            or_(*allows) if allows else false(),
            not_(or_(*denies)) if denies else true(),
            not_(or_(*pending)) if pending else true(),
        )

    def readable_scope(self, resource, fields):
        restrictive = [
            self.predicate(rule)
            for rule in self.applicable(resource, "read")
            if rule.effect == "allow"
            and any(rule.fields.get(field, "hidden") not in {"read", "write"} for field in fields)
        ]
        return self.scope(resource, "read") & (not_(or_(*restrictive)) if restrictive else true())

    def _matches_data(self, rule, data):
        # Evaluate the same SQL predicate against bound candidate data, avoiding Python/SQL drift.
        from sqlalchemy import literal, select
        from sqlalchemy.sql import visitors

        model = RESOURCES[rule.resource].model

        def replace(node):
            if getattr(node, "table", None) is model.__table__:
                return literal(data.get(node.name), type_=node.type)
            return None

        expression = visitors.replacement_traverse(self.predicate(rule), {}, replace)
        return self.db.scalar(select(expression)) is True

    def authorize(self, resource, action, data):
        matching = [r for r in self.applicable(resource, action) if self._matches_data(r, data)]
        allows = [r for r in matching if r.effect == "allow"]
        denied = any(r.effect == "deny" for r in matching)
        allowed = bool(allows) and not denied
        fields = (
            {
                f: min((r.fields.get(f, "hidden") for r in allows), key=LEVEL.get)
                for f in RESOURCES[resource].fields
            }
            if allowed
            else {}
        )
        return {
            "allowed": allowed,
            "reason": "explicit_deny" if denied else "allowed" if allowed else "default_deny",
            "scope": [r.scope for r in allows],
            "fields": fields,
            "requires_approval": any(r.requires_approval for r in allows),
            "policy_ids": [r.id for r in matching],
            "revision": self.revision,
        }

    def project(self, resource, data):
        decision = self.authorize(resource, "read", data)
        if not decision["allowed"] or decision["requires_approval"]:
            return None
        return {
            k: "***" if decision["fields"][k] == "masked" else v
            for k, v in data.items()
            if k not in {"password", "access_token"}
            and decision["fields"].get(k, "hidden") != "hidden"
        }
