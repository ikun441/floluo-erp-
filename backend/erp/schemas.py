from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Strict):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class SubjectRule(Strict):
    kind: Literal["all", "user", "role", "department"]
    id: str | None = None

    @model_validator(mode="after")
    def require_id(self):
        if (self.kind == "all") != (self.id is None):
            raise ValueError("all has no id; other subjects require id")
        return self


class Condition(Strict):
    field: str
    op: Literal["eq", "in", "lt", "lte", "gt", "gte"]
    value: str | int | bool | list[str | int | bool]

    @model_validator(mode="after")
    def valid_operand(self):
        if (self.op == "in") != isinstance(self.value, list):
            raise ValueError("in requires list; other operators require scalar")
        if isinstance(self.value, list) and len(self.value) > 100:
            raise ValueError("too many operands")
        return self


class Rule(Strict):
    id: str = Field(min_length=1, max_length=80)
    subject: SubjectRule
    effect: Literal["allow", "deny"]
    resource: str
    actions: list[str] = Field(min_length=1, max_length=10)
    scope: Literal["own", "department", "departments", "records", "all"] = "own"
    scope_ids: list[str] = Field(default_factory=list, max_length=100)
    fields: dict[str, Literal["hidden", "masked", "read", "write"]] = Field(default_factory=dict)
    conditions: list[Condition] = Field(default_factory=list, max_length=20)
    requires_approval: bool = False


class Publish(Strict):
    expected_revision: int = Field(ge=0)
    rules: list[Rule] = Field(max_length=500)


class Simulate(Strict):
    user_id: str
    resource: str
    action: str
    record_id: str


class CreateEntity(Strict):
    data: dict[str, Any]


class PatchEntity(CreateEntity):
    version: int = Field(ge=1)


class ProductInput(Strict):
    sku: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    unit: str = Field(min_length=1, max_length=30)
    owner_id: str
    department_id: str | None = None
    active: bool = True


class UserInput(Strict):
    username: str = Field(pattern=r"^[a-zA-Z0-9_.-]{3,80}$")
    password: str = Field(min_length=14, max_length=256)
    department_id: str | None = None
    position_id: str | None = None
    supervisor_id: str | None = None
    active: bool = True
    role_ids: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("username")
    @classmethod
    def normalize(cls, value):
        return value.lower()


class NameInput(Strict):
    name: str = Field(min_length=1, max_length=120)


class DepartmentInput(NameInput):
    parent_id: str | None = None
