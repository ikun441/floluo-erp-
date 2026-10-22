"""Bounded, permission-filtered aggregates; no alternate business data access path."""

import csv
import io
from contextlib import contextmanager
from time import monotonic

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from . import procurement, sales
from .business_models import Warehouse
from .models import Product
from .order_support import wire
from .permissions import RESOURCES

SOURCE_LIMIT = 10000
GROUP_LIMIT = 200
QUERY_SECONDS = 5
REPORTS = {
    "inventory": "inventory_balances",
    "movements": "stock_movements",
    "purchases": "purchase_orders",
    "sales": "sales_orders",
}
ORDER_STATUSES = {
    "purchases": {"draft", "submitted", "approved", "partially_received", "received", "cancelled"},
    "sales": {"draft", "submitted", "approved", "partially_shipped", "shipped", "cancelled"},
}


@contextmanager
def query_budget(db):
    """Bound database work, restoring connection settings before returning to the pool."""
    connection = db.connection()
    driver = connection.connection.driver_connection
    sqlite = connection.dialect.name == "sqlite"
    if sqlite:
        deadline = monotonic() + QUERY_SECONDS
        driver.set_progress_handler(lambda: int(monotonic() >= deadline), 1000)
    else:
        previous = db.scalar(text("SHOW statement_timeout"))
        db.execute(
            text("SELECT set_config('statement_timeout', :value, true)"),
            {"value": str(QUERY_SECONDS * 1000)},
        )
    try:
        yield
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == "57014" or (
            sqlite and "interrupted" in str(exc.orig).lower()
        ):
            raise HTTPException(503, "report_query_timeout") from None
        raise
    else:
        if not sqlite:
            db.execute(
                text("SELECT set_config('statement_timeout', :value, true)"), {"value": previous}
            )
    finally:
        if sqlite:
            driver.set_progress_handler(None, 0)


def source(engine, name, metric, filters, exporting):
    resource = REPORTS[name]
    model = RESOURCES[resource].model
    actions = ["read", "report"] + (["export"] if exporting else [])
    for action in actions:
        if not any(
            r.effect == "allow" and not r.requires_approval
            for r in engine.applicable(resource, action)
        ):
            raise HTTPException(403, "report_permission_denied")
    order = name in ORDER_STATUSES
    allowed_filters = {"status", "currency"} if order else {"product_id", "warehouse_id"}
    if name == "movements":
        allowed_filters.add("kind")
    if not set(filters) <= allowed_filters or (not order and metric != "count"):
        raise HTTPException(422, "invalid_report_filter")
    if "status" in filters and filters["status"] not in ORDER_STATUSES[name]:
        raise HTTPException(422, "invalid_report_filter")
    if "kind" in filters and filters["kind"] not in {"purchase_receipt", "sales_shipment"}:
        raise HTTPException(422, "invalid_report_filter")
    if "currency" in filters and (
        len(filters["currency"]) != 3
        or not filters["currency"].isascii()
        or not filters["currency"].isalpha()
        or not filters["currency"].isupper()
    ):
        raise HTTPException(422, "invalid_report_filter")
    if order:
        statement = (
            select(model).where(sales.order_scope(engine))
            if name == "sales"
            else procurement.scoped_statement(engine, resource)
        )
        dimensions = ["status", "currency"]
        fields = set(dimensions)
        if metric == "amount":
            fields |= {"total", "unit_price", "line_amount"}
        columns = [getattr(model, key).label(key) for key in dimensions]
        if metric == "amount":
            columns.append(model.total.label("value"))
    else:
        statement = procurement.scoped_statement(engine, resource)
        statement = (
            statement.join(Product, Product.id == model.product_id)
            .join(Warehouse, Warehouse.id == model.warehouse_id)
            .where(
                engine.readable_scope("products", {"id", "sku", "name", "unit"}),
                engine.readable_scope("warehouses", {"id", "code", "name"}),
            )
        )
        dimensions = [
            "warehouse_id",
            "warehouse_code",
            "warehouse_name",
            "product_id",
            "sku",
            "product_name",
            "unit",
        ]
        columns = [
            model.warehouse_id,
            Warehouse.code.label("warehouse_code"),
            Warehouse.name.label("warehouse_name"),
            model.product_id,
            Product.sku,
            Product.name.label("product_name"),
            Product.unit,
        ]
        fields = {"warehouse_id", "product_id", "quantity"}
        if name == "movements":
            dimensions.append("kind")
            columns.append(model.kind)
            fields.add("kind")
        columns.append(model.quantity.label("value"))
    for action in actions:
        statement = statement.where(engine.field_scope(resource, fields, action))
    for key, value in filters.items():
        statement = statement.where(getattr(model, key) == value)
    return statement.with_only_columns(*columns, maintain_column_froms=True), dimensions


def run(db, engine, name, metric, filters, exporting=False):
    if name not in REPORTS:
        raise HTTPException(404, "report_not_found")
    statement, dimensions = source(engine, name, metric, filters, exporting)
    # A cap is checked before grouping; never publish a silently truncated aggregate.
    bounded = statement.limit(SOURCE_LIMIT + 1).subquery()
    with query_budget(db):
        count = db.scalar(select(func.count()).select_from(bounded))
        if count > SOURCE_LIMIT:
            raise HTTPException(422, "report_source_limit")
        keys = [bounded.c[key] for key in dimensions]
        aggregates = [func.count().label("source_rows")]
        if "value" in bounded.c:
            aggregates.append(
                func.sum(bounded.c.value).label("amount" if metric == "amount" else "quantity")
            )
        rows = (
            db.execute(
                select(*keys, *aggregates).group_by(*keys).order_by(*keys).limit(GROUP_LIMIT + 1)
            )
            .mappings()
            .all()
        )
        if len(rows) > GROUP_LIMIT:
            raise HTTPException(422, "report_group_limit")
    return {
        "report": name,
        "metric": metric,
        "policy_revision": engine.revision,
        "source_rows": count,
        "items": [wire(dict(row)) for row in rows],
        "scope": "eligible_records_only",
        "limits": {"source_rows": SOURCE_LIMIT, "groups": GROUP_LIMIT},
        "columns": dimensions
        + ["source_rows"]
        + (["amount" if metric == "amount" else "quantity"] if "value" in bounded.c else []),
    }


def csv_document(result):
    def cell(value):
        value = str(value)
        # Quoting alone does not stop spreadsheet formulas, including whitespace prefixes.
        probe = value.lstrip("\ufeff \t\r\n\v\f")
        return (
            "'" + value
            if probe.startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n"))
            else value
        )

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(result["columns"])
    writer.writerows(
        [cell(row.get(key, "")) for key in result["columns"]] for row in result["items"]
    )
    return "\ufeff" + output.getvalue()
