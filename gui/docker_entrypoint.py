"""Run the Qt desktop app behind a loopback-only browser VNC session."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

DISPLAY = os.environ.get("DISPLAY", ":99")
DISPLAY_SOCKET = Path("/tmp/.X11-unix") / f"X{DISPLAY.lstrip(':').split('.')[0]}"
DISPLAY_SIZE = os.environ.get("PHISHREPORT_GUI_SIZE", "1440x900x24")


def _validate_display_size(value: str) -> str:
    parts = value.split("x")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError("PHISHREPORT_GUI_SIZE must use WIDTHxHEIGHTxDEPTH format.")
    width, height, depth = map(int, parts)
    if not (800 <= width <= 3840 and 600 <= height <= 2160 and depth in (16, 24, 32)):
        raise ValueError("PHISHREPORT_GUI_SIZE is outside the supported display range.")
    return value


def _wait_for_display(processes: list[subprocess.Popen[bytes]], timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for process in processes:
            if process.poll() is not None:
                raise RuntimeError(
                    f"Display service exited early with status {process.returncode}."
                )
        if DISPLAY_SOCKET.exists():
            return
        time.sleep(0.1)
    raise RuntimeError("The virtual display did not become ready.")


def _wait_for_port(
    port: int, processes: list[subprocess.Popen[bytes]], timeout: float = 15
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for process in processes:
            if process.poll() is not None:
                raise RuntimeError(
                    f"Display service exited early with status {process.returncode}."
                )
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"Display service did not open port {port}.")


def _stop_processes(processes: list[subprocess.Popen[bytes]]) -> None:
    for process in reversed(processes):
        if process.poll() is None:
            process.terminate()
    for process in reversed(processes):
        if process.poll() is None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main() -> int:
    _validate_display_size(DISPLAY_SIZE)
    os.environ.setdefault("PHISHREPORT_API_URL", "http://host.docker.internal:8000")
    os.environ["DISPLAY"] = DISPLAY

    processes: list[subprocess.Popen[bytes]] = []
    gui: subprocess.Popen[bytes] | None = None

    def stop_gui(_signum: int, _frame: object) -> None:
        if gui and gui.poll() is None:
            gui.terminate()

    signal.signal(signal.SIGTERM, stop_gui)
    signal.signal(signal.SIGINT, stop_gui)

    try:
        processes.append(
            subprocess.Popen(
                [
                    "Xvfb",
                    DISPLAY,
                    "-screen",
                    "0",
                    DISPLAY_SIZE,
                    "-nolisten",
                    "tcp",
                    "-ac",
                ]
            )
        )
        _wait_for_display(processes)
        processes.append(subprocess.Popen(["openbox"]))
        processes.append(
            subprocess.Popen(
                [
                    "x11vnc",
                    "-display",
                    DISPLAY,
                    "-rfbport",
                    "5900",
                    "-localhost",
                    "-forever",
                    "-shared",
                    "-nopw",
                    "-quiet",
                ]
            )
        )
        _wait_for_port(5900, processes)
        processes.append(
            subprocess.Popen(
                [
                    "websockify",
                    "--web=/usr/share/novnc",
                    "0.0.0.0:6080",
                    "127.0.0.1:5900",
                ]
            )
        )
        _wait_for_port(6080, processes)

        print(
            "PhishReport GUI is ready at "
            "http://localhost:6080/vnc.html?autoconnect=true&resize=scale",
            flush=True,
        )
        gui = subprocess.Popen([sys.executable, "-m", "gui.main"])
        while gui.poll() is None:
            for process in processes:
                if process.poll() is not None:
                    raise RuntimeError(
                        f"Desktop display service exited with status {process.returncode}."
                    )
            time.sleep(0.2)
        return gui.returncode or 0
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Could not start the PhishReport Docker GUI: {error}", file=sys.stderr)
        return 1
    finally:
        if gui and gui.poll() is None:
            gui.terminate()
            try:
                gui.wait(timeout=5)
            except subprocess.TimeoutExpired:
                gui.kill()
                gui.wait()
        _stop_processes(processes)


if __name__ == "__main__":
    raise SystemExit(main())
