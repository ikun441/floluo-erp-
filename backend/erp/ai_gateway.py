"""Current subject + current policy + explicit AI capability; no model-controlled authority."""

from time import monotonic

from fastapi import HTTPException

from . import reports
from .ai_schemas import TOOL_RESOURCES, AIIntent
from .message_service import query_business
from .permissions import LEVEL, Engine


class ToolEngine(Engine):
    """Intersect one tool's read authority without altering its related-resource read scopes."""

    def __init__(self, engine, resource):
        self.base, self.resource = engine, resource
        self.db, self.who, self.rules, self.revision = (
            engine.db,
            engine.who,
            engine.rules,
            engine.revision,
        )

    def applicable(self, resource, action):
        rules = self.base.applicable(resource, action)
        if resource == self.resource and action == "read":
            rules = rules + self.base.applicable(resource, "ai_query")
        return rules

    def scope(self, resource, action):
        if resource == self.resource and action == "read":
            return self.base.scope(resource, "read") & self.base.field_scope(
                resource, set(), "ai_query"
            )
        return self.base.scope(resource, action)

    def authorize(self, resource, action, data):
        decision = self.base.authorize(resource, action, data)
        if resource != self.resource or action != "read":
            return decision
        ai = self.base.authorize(resource, "ai_query", data)
        allowed = decision["allowed"] and ai["allowed"]
        return {
            **decision,
            "allowed": allowed,
            "reason": (
                "allowed"
                if allowed
                else "explicit_deny"
                if "explicit_deny" in {decision["reason"], ai["reason"]}
                else "default_deny"
            ),
            "requires_approval": decision["requires_approval"] or ai["requires_approval"],
            "fields": {
                key: min(decision["fields"][key], ai["fields"][key], key=LEVEL.get)
                for key in decision["fields"]
            }
            if allowed
            else {},
            "policy_ids": sorted(set(decision["policy_ids"] + ai["policy_ids"])),
        }


def execute(db, engine, intent: AIIntent, allowed_tools):
    tool, resource = TOOL_RESOURCES[intent.resource]
    if tool not in allowed_tools:
        raise HTTPException(403, "ai_tool_disabled")
    for action in ("read", "ai_query"):
        if not any(
            r.effect == "allow" and not r.requires_approval
            for r in engine.applicable(resource, action)
        ):
            raise HTTPException(403, "ai_tool_denied")
    bounded = ToolEngine(engine, resource)
    start = monotonic()
    if intent.resource == "sales_summary":
        values = dict(intent.arguments)
        metric = values.pop("metric", "count")
        result = reports.run(db, bounded, "sales", metric, values)
    else:
        with reports.query_budget(db):
            result = query_business(db, bounded, intent)
    if monotonic() - start > 5:
        raise HTTPException(503, "report_query_timeout")
    return {"tool": tool, "policy_revision": engine.revision, "result": result}
