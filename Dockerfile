# CLI image remains the default build target.
FROM python:3.14-slim AS base

WORKDIR /app
# The CLI runs from /data, so the package must be importable from /app.
ENV PYTHONPATH=/app

COPY --from=ghcr.io/astral-sh/uv:0.12.16 /uv /uvx /bin/

# Install the project dependencies first for better Docker layer caching.
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

COPY . .

FROM base AS telegram
RUN mkdir -p /data
ENV PHISHREPORT_REPORTS_PATH=/data/reports.json \
    PHISHREPORT_GMAIL_PATH=/data/gmail_accounts.json \
    PHISHREPORT_FEEDBACK_PATH=/data/feedback.json \
    PYTHONUNBUFFERED=1
CMD ["python", "-m", "phishreport.bot"]

FROM base AS all
RUN mkdir -p /data
# SQLite is the safe default when the CLI and bot write the same history.
# An explicit PHISHREPORT_STORAGE from .env still overrides it at runtime.
ENV PHISHREPORT_STORAGE=sqlite \
    PHISHREPORT_REPORTS_PATH=/data/reports.json \
    PHISHREPORT_GMAIL_PATH=/data/gmail_accounts.json \
    PYTHONUNBUFFERED=1
# The CLI file-upload option serves a one-shot page on port 8000.
EXPOSE 8000
CMD ["python", "-m", "phishreport.combined"]

FROM base AS cli

# The file-upload option serves a one-shot page on port 8000.
EXPOSE 8000
CMD ["python", "-m", "phishreport.cli"]
