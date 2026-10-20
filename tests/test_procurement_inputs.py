import json
from decimal import Decimal
from pathlib import Path

import pytest
from erp.business_schemas import LineInput, ReceiveInput
from pydantic import ValidationError

CASES = json.loads((Path(__file__).parent / "fixtures/procurement_cases.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_decimal_boundaries(case):
    if case["valid"]:
        line = LineInput.model_validate(case["input"])
        assert line.quantity == Decimal(str(case["input"]["quantity"]))
        assert line.unit_price == Decimal(str(case["input"]["unit_price"]))
    else:
        with pytest.raises(ValidationError):
            LineInput.model_validate(case["input"])


@pytest.mark.parametrize("value", [True, False, "NaN", "Infinity", "100000000000000.0000"])
def test_nonfinite_boolean_or_overflow_quantity_is_rejected(value):
    with pytest.raises(ValidationError):
        LineInput(product_id="fixture-product", quantity=value, unit_price="1.00")


def test_receipt_duplicate_lines_rejected():
    with pytest.raises(ValidationError):
        ReceiveInput(version=1, warehouse_id="w", lines=[{"line_id": "same", "quantity": 1}] * 2)
