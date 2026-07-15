FROM python:3.12-slim

WORKDIR /srv
ENV PYTHONUNBUFFERED=1

# uv is the installer (replaces bare `pip`): no "running pip as root" / "upgrade
# pip" notices, deterministic resolution, and a much faster Cloud Build layer.
# Pinned for reproducibility — bump deliberately.
COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_NO_CACHE=1

COPY pyproject.toml ./
COPY app ./app
# --system: install into the image's interpreter (no venv needed in a container).
RUN uv pip install --system .

# Cloud Run service entrypoint. Jobs override with:
#   --command python --args -m,app.jobs.<name>
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
