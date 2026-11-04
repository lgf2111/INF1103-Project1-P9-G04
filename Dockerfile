# CLI image remains the default build target.
FROM python:3.12-slim AS base

WORKDIR /app

# Install the CLI/test dependencies first for better Docker layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

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

RUN pip install --no-cache-dir --retries 5 --timeout 120 -r desktop_gui/requirements.txt

ENV DISPLAY=host.docker.internal:0
ENV QT_X11_NO_MITSHM=1
CMD ["python", "-m", "desktop_gui.main"]

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
CMD ["python", "-m", "desktop_gui.docker_entrypoint"]

FROM base AS cli

# The file-upload option serves a one-shot page on port 8000.
EXPOSE 8000
CMD ["python", "app/main.py"]
