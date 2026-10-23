from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from .messaging_api import StrictInput

Tool = Literal["query_inventory", "query_purchase_orders", "query_sales_summary"]
TOOL_RESOURCES = {
    "inventory": ("query_inventory", "inventory_balances"),
    "purchase_orders": ("query_purchase_orders", "purchase_orders"),
    "sales_summary": ("query_sales_summary", "sales_orders"),
}


class ConfigurationValues(StrictInput):
    enabled: bool = False
    base_url: str = Field("", max_length=500)
    model: str = Field("", max_length=120)
    timeout_seconds: int = Field(10, ge=2, le=20)
    tools: list[Tool] = Field(default_factory=list, max_length=3)

    @field_validator("model", "base_url")
    @classmethod
    def trimmed(cls, value):
        if value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("invalid configuration text")
        return value

    @field_validator("tools")
    @classmethod
    def unique(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("duplicate tools")
        return value


class ConfigurationUpdate(StrictInput):
    version: int = Field(ge=1)
    values: ConfigurationValues


class ParseInput(StrictInput):
    text: str = Field(min_length=1, max_length=4096)
    consent: Literal[True]

    @field_validator("consent", mode="before")
    @classmethod
    def explicit_consent(cls, value):
        if value is not True:
            raise ValueError("explicit consent required")
        return value

    @field_validator("text")
    @classmethod
    def meaningful(cls, value):
        if not value.strip() or any(ord(c) < 32 and c not in "\r\n\t" for c in value):
            raise ValueError("invalid text")
        return value


class InventoryArguments(StrictInput):
    query: str = Field(min_length=1, max_length=160)

    @field_validator("query")
    @classmethod
    def meaningful(cls, value):
        if not value.strip():
            raise ValueError("blank query")
        return value


class PurchaseArguments(StrictInput):
    number: str | None = Field(None, min_length=1, max_length=50)


class SalesArguments(StrictInput):
    metric: Literal["count", "amount"] = "count"
    status: (
        Literal["draft", "submitted", "approved", "partially_shipped", "shipped", "cancelled"]
        | None
    ) = None
    currency: str | None = Field(None, pattern=r"^[A-Z]{3}$")


class AIIntent(StrictInput):
    operation: Literal["query"]
    resource: Literal["inventory", "purchase_orders", "sales_summary"]
    arguments: dict[str, str]
    references: dict[str, str]
    confidence: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    parser_source: Literal["ai"]

    @model_validator(mode="after")
    def bounded_arguments(self):
        if self.references:
            raise ValueError("references not supported for read-only AI")
        kind = {
            "inventory": InventoryArguments,
            "purchase_orders": PurchaseArguments,
            "sales_summary": SalesArguments,
        }[self.resource]
        kind.model_validate(self.arguments)
        return self


class RequestVersion(StrictInput):
    version: int = Field(ge=1)
