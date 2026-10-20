FROM python:3.13-slim
WORKDIR /app
RUN pip install --no-cache-dir uv==0.13.1
COPY pyproject.toml uv.lock ./
COPY backend ./backend
COPY alembic.ini ./
RUN uv sync --frozen --no-dev && useradd --uid 10001 --create-home app
USER app
ENV PATH="/app/.venv/bin:$PATH"
CMD ["uvicorn", "erp.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
