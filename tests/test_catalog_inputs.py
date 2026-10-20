import json
from pathlib import Path

import pytest
from erp.schemas import ProductInput
from pydantic import ValidationError

CASES = json.loads((Path(__file__).parent / "fixtures/catalog_cases.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_catalog_input_boundaries(case):
    values = {**case["input"], "owner_id": "fixture-owner"}
    if case["valid"]:
        product = ProductInput.model_validate(values)
        assert product.sku == case["input"]["sku"]
        assert product.name == case["input"]["name"]
    else:
        with pytest.raises(ValidationError):
            ProductInput.model_validate(values)
