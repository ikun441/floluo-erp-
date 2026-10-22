from typing import Annotated, Literal

from fastapi import Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from . import reports
from .permissions import Engine


class ReportQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: Literal["count", "amount"] = "count"
    warehouse_id: str | None = Field(None, min_length=1, max_length=80)
    product_id: str | None = Field(None, min_length=1, max_length=80)
    status: str | None = Field(None, min_length=1, max_length=30)
    currency: str | None = Field(None, min_length=1, max_length=3)
    kind: str | None = Field(None, min_length=1, max_length=30)


def register(app, database, authorized_engine):
    def execute(name, query, request, engine, db, exporting):
        values = query.model_dump(exclude_none=True)
        metric = values.pop("metric")
        result = reports.run(db, engine, name, metric, values, exporting)
        request.state.audit_details = {
            "report": name,
            "metric": metric,
            "export": exporting,
            "groups": len(result["items"]),
            "source_rows": result["source_rows"],
            "policy_revision": engine.revision,
            "filter_fields": sorted(values),
        }
        if exporting:
            return Response(
                reports.csv_document(result),
                media_type="text/csv; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{name}.csv"'},
            )
        return result

    @app.get("/api/v1/reports/{name}")
    def report(
        name: str,
        request: Request,
        query: Annotated[ReportQuery, Query()],
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        return execute(name, query, request, engine, db, False)

    @app.get("/api/v1/reports/{name}/export")
    def export(
        name: str,
        request: Request,
        query: Annotated[ReportQuery, Query()],
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        return execute(name, query, request, engine, db, True)
