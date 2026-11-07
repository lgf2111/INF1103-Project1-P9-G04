# CLI image remains the default build target.
FROM python:3.14-slim AS base

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.12.16 /uv /uvx /bin/

# Install the project dependencies first for better Docker layer caching.
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

COPY . .

FROM base AS telegram
ENV PHISHREPORT_REPORTS_PATH=/data/reports.json
CMD ["python", "-m", "app_gui.main"]

FROM base AS cli

# The file-upload option serves a one-shot page on port 8000.
EXPOSE 8000
CMD ["python", "app_cli/main.py"]
