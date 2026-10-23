"""Serve an isolated loopback-only browser fixture, never a production database."""

import json
import os
import tempfile
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[2]
    runtime = root / ".test-runtime"
    runtime.mkdir(exist_ok=True, mode=0o700)
    directory = Path(tempfile.mkdtemp(prefix="browser-", dir=runtime))
    os.environ["DATABASE_URL"] = "sqlite:///" + str(directory / "browser.db")
    os.environ["APP_ORIGIN"] = "http://127.0.0.1:3000"
    os.environ["SECURE_COOKIES"] = "false"

    from ai_fixture import start

    model_fixture = start()
    os.environ["AI_ALLOWED_BASE_URLS"] = json.dumps(
        [f"http://127.0.0.1:{model_fixture.server_port}/v1"]
    )
    os.environ["AI_API_KEY"] = ""

    import uvicorn
    from alembic import command
    from alembic.config import Config
    from erp.bootstrap import initialize
    from erp.main import create_app
    from sqlalchemy.orm import Session

    command.upgrade(Config(str(root / "alembic.ini")), "head")
    app = create_app()
    with Session(app.state.engine) as db:
        initialize(db, "browser_admin", "Browser-fixture-" + "x" * 20)
    print("Isolated browser test backend ready on 127.0.0.1:8000")
    try:
        uvicorn.run(app, host="127.0.0.1", port=8000, access_log=False)
    finally:
        model_fixture.shutdown()
        model_fixture.server_close()


if __name__ == "__main__":
    main()
