"""Prepare a local development environment and run the API and web application."""

from __future__ import annotations

import getpass
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
ENV_FILE = ROOT / ".env"
FRONTEND = ROOT / "frontend"
MIN_PYTHON = (3, 12)


def run(command: list[str], *, cwd: Path = ROOT, env=None) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


def python_in_venv() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def ensure_virtualenv() -> Path:
    if sys.version_info < MIN_PYTHON:
        raise SystemExit(
            f"Python 3.12+ is required; found {platform.python_version()}. "
            "Install Python 3.12 or newer and run this script again."
        )
    executable = python_in_venv()
    if not executable.exists():
        print("Creating Python virtual environment in .venv ...", flush=True)
        run([sys.executable, "-m", "venv", str(VENV)])
    if Path(sys.prefix).resolve() != VENV.resolve():
        env = os.environ.copy()
        os.execve(str(executable), [str(executable), str(Path(__file__).resolve())], env)
    return executable


def ensure_dependencies(python: Path) -> None:
    print("Checking and installing backend dependencies ...", flush=True)
    run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "-e", "."])
    npm = shutil.which("npm")
    node = shutil.which("node")
    if not npm or not node:
        raise SystemExit("Node.js and npm are required. Install Node.js 24+ and retry.")
    node_version = subprocess.check_output([node, "--version"], text=True).strip().lstrip("v")
    if tuple(int(x) for x in node_version.split(".")[:1]) < (24,):
        raise SystemExit(f"Node.js 24+ is required; found {node_version}.")
    npm_check = subprocess.run(
        [npm, "ls", "--depth=0"],
        cwd=FRONTEND,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=os.name == "nt",
    )
    if npm_check.returncode:
        print("Installing frontend dependencies with npm ci ...", flush=True)
        subprocess.run([npm, "ci"], cwd=FRONTEND, check=True, shell=os.name == "nt")


def ensure_environment(python: Path) -> dict[str, str]:
    if not ENV_FILE.exists():
        print("Creating private local environment settings ...", flush=True)
        run([str(python), str(ROOT / "scripts" / "init_env.py")])
    values: dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    password = values.get("POSTGRES_PASSWORD", "")
    if not values.get("DATABASE_URL"):
        if not password:
            raise SystemExit(".env must define DATABASE_URL or POSTGRES_PASSWORD.")
        port = values.get("ERP_DB_PORT", "5432")
        values["DATABASE_URL"] = f"postgresql+psycopg://floluo:{password}@127.0.0.1:{port}/floluo"
    return values


def can_connect(database_url: str) -> bool:
    from sqlalchemy import create_engine, text

    engine = create_engine(database_url, pool_pre_ping=True, connect_args={"connect_timeout": 2})
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()


def ensure_database(python: Path, settings: dict[str, str], env: dict[str, str]) -> None:
    database_url = settings["DATABASE_URL"]
    if not can_connect(database_url):
        parsed = urlparse(database_url)
        if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise SystemExit(
                "Configured database is unreachable and is not a local address. "
                "Check DATABASE_URL and start the database manually."
            )
        compose = shutil.which("docker")
        if not compose:
            raise SystemExit(
                "The configured local PostgreSQL database is unavailable and Docker "
                "was not found. Install/start PostgreSQL or Docker Compose, then retry."
            )
        print("Starting the local PostgreSQL service with Docker Compose ...", flush=True)
        run([compose, "compose", "up", "-d", "postgres"], env=env)

        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if can_connect(database_url):
                break
            time.sleep(2)
        else:
            raise SystemExit(
                "PostgreSQL did not become ready. Inspect docker compose logs postgres."
            )

    child_env = env | {
        "DATABASE_URL": database_url,
        "APP_ORIGIN": "http://127.0.0.1:3000",
        "SECURE_COOKIES": "false",
        "PYTHONPATH": str(ROOT / "backend"),
    }
    print("Applying database migrations ...", flush=True)
    run([str(python), "-m", "alembic", "upgrade", "head"], env=child_env)
    bootstrap_if_needed(child_env)


def bootstrap_if_needed(env: dict[str, str]) -> None:
    sys.path.insert(0, str(ROOT / "backend"))
    from erp.database import make_engine
    from erp.models import Gate, User
    from sqlalchemy import inspect, select, text
    from sqlalchemy.orm import Session

    engine = make_engine(env["DATABASE_URL"])
    try:
        with Session(engine) as db:
            gate = db.get(Gate, 1)
            users = db.scalar(select(User.id).limit(1))
            if gate is None:
                raise SystemExit("Database migrations completed without the authorization gate.")
            if gate.revision_id:
                print("Database is already initialized.", flush=True)
                return
            occupied_tables = []
            inspector = inspect(engine)
            for table in inspector.get_table_names():
                if table in {"alembic_version", "authorization_gate"}:
                    continue
                quoted_table = engine.dialect.identifier_preparer.quote(table)
                if db.execute(text(f"SELECT 1 FROM {quoted_table} LIMIT 1")).first():
                    occupied_tables.append(table)
            if users is not None or occupied_tables:
                raise SystemExit(
                    "Database contains records but no active policy revision was found; "
                    "refusing to bootstrap."
                )
    finally:
        engine.dispose()

    print("No administrator exists yet; create the first administrator now.")
    username = input("Administrator username: ").strip()
    if not username:
        raise SystemExit("Administrator username cannot be empty.")
    password = getpass.getpass("Administrator password (at least 14 characters): ")
    if len(password) < 14:
        raise SystemExit("Password must be at least 14 characters.")
    if password != getpass.getpass("Confirm administrator password: "):
        raise SystemExit("Passwords do not match.")
    from erp.bootstrap import initialize

    engine = make_engine(env["DATABASE_URL"])
    try:
        with Session(engine) as db:
            initialize(db, username, password)
    finally:
        engine.dispose()
    print("Administrator initialized; no sample business data was created.", flush=True)


def wait_for(url: str, process: subprocess.Popen, label: str) -> None:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SystemExit(f"{label} exited during startup with code {process.returncode}.")
        try:
            with urllib.request.urlopen(url, timeout=2):
                return
        except (OSError, urllib.error.URLError):
            time.sleep(1)
    raise SystemExit(f"{label} did not become ready at {url}.")


def serve(python: Path, settings: dict[str, str]) -> None:
    env = (
        os.environ.copy()
        | settings
        | {
            "DATABASE_URL": settings["DATABASE_URL"],
            "APP_ORIGIN": "http://127.0.0.1:3000",
            "SECURE_COOKIES": "false",
            "AI_API_KEY": "",
            "PYTHONPATH": str(ROOT / "backend"),
            "BACKEND_URL": "http://127.0.0.1:8000",
            "HOSTNAME": "127.0.0.1",
            "PORT": "3000",
        }
    )
    node = shutil.which("node")
    next_cli = FRONTEND / "node_modules" / "next" / "dist" / "bin" / "next"
    if not node or not next_cli.exists():
        raise SystemExit("Node.js or the Next.js CLI is missing after dependency installation.")
    processes: list[subprocess.Popen] = []
    try:
        processes.append(
            subprocess.Popen(
                [
                    str(python),
                    "-m",
                    "uvicorn",
                    "erp.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8000",
                    "--no-access-log",
                ],
                cwd=ROOT,
                env=env,
            )
        )
        wait_for("http://127.0.0.1:8000/health/ready", processes[-1], "ERP API")
        processes.append(
            subprocess.Popen(
                [node, str(next_cli), "dev", "--hostname", "127.0.0.1"],
                cwd=FRONTEND,
                env=env,
            )
        )
        wait_for("http://127.0.0.1:3000", processes[-1], "Web application")
        print()
        print("弗洛洛 ERP is ready")
        print("Web:       http://127.0.0.1:3000")
        print("API docs:  http://127.0.0.1:8000/docs")
        print("Database:  configured local PostgreSQL")
        print("AI:        disabled (optional)")
        print("Press Ctrl+C to stop the API and web application.")
        while all(process.poll() is None for process in processes):
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping ERP API and web application ...", flush=True)
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
        for process in reversed(processes):
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


def main() -> None:
    for port, label in ((8000, "ERP API"), (3000, "web application")):
        with socket.socket() as listener:
            try:
                listener.bind(("127.0.0.1", port))
            except OSError as exc:
                raise SystemExit(
                    f"Port {port} for the {label} is already in use; stop that service "
                    "or choose another port before starting."
                ) from exc
    python = ensure_virtualenv()
    ensure_dependencies(python)
    settings = ensure_environment(python)
    env = os.environ.copy() | settings
    ensure_database(python, settings, env)
    serve(python, settings)


if __name__ == "__main__":
    main()
