"""Authenticated offline interpretation; every execution reparses and reauthorizes."""

from dataclasses import asdict

from fastapi import Depends, HTTPException
from pydantic import Field
from sqlalchemy.orm import Session

from . import message_operations
from .local_parser import parse_message
from .message_service import query_business
from .messaging_api import StrictInput
from .permissions import Engine


class TextInput(StrictInput):
    text: str = Field(min_length=1, max_length=4096)


def intent_for(text):
    result = parse_message(text)
    if result.intent is None:
        raise HTTPException(422, "local_intent_not_recognized")
    return result


def register(app, database, authorized_engine):
    @app.post("/api/v1/intents/parse")
    def parse(body: TextInput, engine: Engine = Depends(authorized_engine)):
        result = intent_for(body.text)
        return {"intent": asdict(result.intent), "missing": result.missing}

    @app.post("/api/v1/intents/query")
    def query(
        body: TextInput,
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        intent = intent_for(body.text).intent
        if intent.operation != "query":
            raise HTTPException(422, "query_intent_required")
        return query_business(db, engine, intent)

    @app.post("/api/v1/intents/requests")
    def create_request(
        body: TextInput,
        engine: Engine = Depends(authorized_engine),
        db: Session = Depends(database, scope="function"),
    ):
        intent = intent_for(body.text).intent
        if intent.operation != "create" or intent.resource != "purchase_orders":
            raise HTTPException(422, "purchase_intent_required")
        row = message_operations.create(db, engine, {**intent.arguments, **intent.references})
        return message_operations.view(db, engine, row)
