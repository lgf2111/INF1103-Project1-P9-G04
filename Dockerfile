# CLI image remains the default build target.
FROM python:3.14-slim AS base

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.12.16 /uv /uvx /bin/

# Install the project dependencies first for better Docker layer caching.
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

COPY . .

FROM base AS gui-native

RUN apt-get update && apt-get install -y --no-install-recommends \
    libdbus-1-3 \
    libegl1 \
    libfontconfig1 \
    libfreetype6 \
    libgl1 \
    libglib2.0-0 \
    libice6 \
    libsm6 \
    libx11-xcb1 \
    libxcb-cursor0 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-randr0 \
    libxcb-render-util0 \
    libxcb-shape0 \
    libxcb-sync1 \
    libxcb-util1 \
    libxcb-xfixes0 \
    libxcb-xinerama0 \
    libxcb-xkb1 \
    libxkbcommon-x11-0 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

ENV DISPLAY=host.docker.internal:0
ENV QT_X11_NO_MITSHM=1
CMD ["python", "-m", "app_gui.main"]

FROM gui-native AS gui

RUN apt-get update && apt-get install -y --no-install-recommends \
    dbus-x11 \
    novnc \
    openbox \
    websockify \
    x11vnc \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

ENV DISPLAY=:99
EXPOSE 6080
CMD ["python", "-m", "app_gui.docker_entrypoint"]

FROM base AS cli

# The file-upload option serves a one-shot page on port 8000.
EXPOSE 8000
CMD ["python", "app_cli/main.py"]
