"""A small typed policy language compiled to bound SQL expressions, never evaluated code."""
from dataclasses import dataclass
from sqlalchemy import and_, false, not_, or_, select, true
from sqlalchemy.orm import Session
from .models import Department, Gate, PolicyRevision, Position, Product, Role, User, UserRole
from .schemas import Rule


@dataclass(frozen=True)
class Resource:
    model: type
    fields: frozenset[str]
    actions: frozenset[str] = frozenset({"read", "create", "update"})
    owner_column: str | None = None
    department_column: str | None = None


RESOURCES = {
    "products": Resource(Product, frozenset({"id", "version", "sku", "name", "unit", "owner_id", "department_id", "active"}), owner_column="owner_id", department_column="department_id"),
    "users": Resource(User, frozenset({"id", "version", "username", "department_id", "position_id", "supervisor_id", "active", "role_ids", "password"}), owner_column="id", department_column="department_id"),
    "departments": Resource(Department, frozenset({"id", "version", "name", "parent_id"})),
    "positions": Resource(Position, frozenset({"id", "version", "name"})),
    "roles": Resource(Role, frozenset({"id", "version", "name"}), frozenset({"read", "create", "update", "assign"})),
    "policies": Resource(PolicyRevision, frozenset({"id", "number", "rules"}), frozenset({"read", "publish", "simulate"})),
}
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
            if c.field not in resource.fields or c.field in {"password", "role_ids", "rules"}:
                raise ValueError("unsupported condition field")
            column = getattr(resource.model, c.field)
            python_type = column.type.python_type
            values = c.value if isinstance(c.value, list) else [c.value]
            if any(type(v) is not python_type for v in values):
                raise ValueError("condition value type does not match field")
            if python_type is bool and c.op not in {"eq", "in"}:
                raise ValueError("boolean ordering is not supported")
        if rule.fields.get("password", "hidden") in {"masked", "read"}:
            raise ValueError("password is write-only")


def conflicts(rules: list[Rule]):
    return [{"allow": a.id, "deny": b.id, "reason": "potential overlap; explicit deny takes priority"}
            for a in rules if a.effect == "allow"
            for b in rules if b.effect == "deny" and a.resource == b.resource and set(a.actions) & set(b.actions)]


class Engine:
    def __init__(self, db: Session, who: Subject):
        self.db, self.who = db, who
        gate = db.get(Gate, 1)
        rev = db.get(PolicyRevision, gate.revision_id) if gate and gate.revision_id else None
        self.revision = rev.number if rev else 0
        self.rules = [Rule.model_validate(r) for r in rev.rules] if rev else []
        validate_rules(self.rules)

    def applicable(self, resource, action):
        if not self.who.active or resource not in RESOURCES or action not in RESOURCES[resource].actions:
            return []
        def matches(s):
            return (s.kind == "all" or s.kind == "user" and s.id == self.who.id
                    or s.kind == "role" and s.id in self.who.roles
                    or s.kind == "department" and self.who.department_id is not None and s.id == self.who.department_id)
        return [r for r in self.rules if r.resource == resource and action in r.actions and matches(r.subject)]

    def predicate(self, rule):
        res = RESOURCES[rule.resource]
        model = res.model
        scope = true()
        if rule.scope == "own":
            scope = getattr(model, res.owner_column) == self.who.id
        elif rule.scope == "department":
            scope = false() if self.who.department_id is None else getattr(model, res.department_column) == self.who.department_id
        elif rule.scope == "departments":
            scope = getattr(model, res.department_column).in_(rule.scope_ids)
        elif rule.scope == "records":
            scope = model.id.in_(rule.scope_ids)
        conditions = []
        for c in rule.conditions:
            column = getattr(model, c.field)
            conditions.append({"eq": lambda: column == c.value, "in": lambda: column.in_(c.value),
                "lt": lambda: column < c.value, "lte": lambda: column <= c.value,
                "gt": lambda: column > c.value, "gte": lambda: column >= c.value}[c.op]())
        return and_(scope, *conditions)

    def scope(self, resource, action):
        rules = self.applicable(resource, action)
        allows = [self.predicate(r) for r in rules if r.effect == "allow"]
        denies = [self.predicate(r) for r in rules if r.effect == "deny"]
        return and_(or_(*allows) if allows else false(), not_(or_(*denies)) if denies else true())

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
        fields = {f: min((r.fields.get(f, "hidden") for r in allows), key=LEVEL.get)
                  for f in RESOURCES[resource].fields} if allowed else {}
        return {"allowed": allowed, "reason": "explicit_deny" if denied else "allowed" if allowed else "default_deny",
                "scope": [r.scope for r in allows], "fields": fields,
                "requires_approval": any(r.requires_approval for r in allows),
                "policy_ids": [r.id for r in matching], "revision": self.revision}

    def project(self, resource, data):
        decision = self.authorize(resource, "read", data)
        if not decision["allowed"]:
            return None
        return {k: "***" if decision["fields"][k] == "masked" else v for k, v in data.items()
                if k != "password" and decision["fields"].get(k, "hidden") != "hidden"}
