from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, field_validator

from .schemas import DepartmentInput, ProductInput, Strict


def exact_decimal(value):
    if isinstance(value, (float, bool)):
        raise ValueError("use decimal strings or integers")
    return value


Quantity = Annotated[
    Decimal,
    BeforeValidator(exact_decimal),
    Field(gt=0, max_digits=18, decimal_places=4, allow_inf_nan=False),
]
Price = Annotated[
    Decimal,
    BeforeValidator(exact_decimal),
    Field(ge=0, max_digits=18, decimal_places=2, allow_inf_nan=False),
]


class CategoryInput(DepartmentInput):
    pass


class OwnedInput(Strict):
    owner_id: str
    department_id: str | None = None
    active: bool = True


class WarehouseInput(OwnedInput):
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)


class SupplierInput(WarehouseInput):
    contact: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=60)


class ClassifiedProductInput(ProductInput):
    category_id: str | None = None


class LineInput(Strict):
    product_id: str
    quantity: Quantity
    unit_price: Price


class OrderInput(Strict):
    supplier_id: str
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    note: str = Field(default="", max_length=2000)
    lines: list[LineInput] = Field(min_length=1, max_length=100)


class OrderUpdate(OrderInput):
    version: int = Field(ge=1)


class Transition(Strict):
    version: int = Field(ge=1)


class ReceiveLine(Strict):
    line_id: str
    quantity: Quantity


class ReceiveInput(Transition):
    warehouse_id: str
    lines: list[ReceiveLine] = Field(min_length=1, max_length=100)

    @field_validator("lines")
    @classmethod
    def unique_lines(cls, value):
        if len({row.line_id for row in value}) != len(value):
            raise ValueError("duplicate receipt line")
        return value


class ConfigurationValues(Strict):
    supported_currencies: list[Annotated[str, Field(pattern=r"^[A-Z]{3}$")]] = Field(
        default_factory=list, max_length=30
    )
    tax_mode: Literal["unconfigured", "no_tax"] = "unconfigured"
    require_separate_approver: bool = True

    @field_validator("supported_currencies")
    @classmethod
    def unique_currencies(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("duplicate currencies")
        return value


class ConfigurationUpdate(Strict):
    version: int = Field(ge=1)
    values: ConfigurationValues
