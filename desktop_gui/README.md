# PhishReport desktop authentication GUI

The desktop GUI is a separate Python application. It adds sign-in, account creation, and password reset screens while leaving the existing CLI and its dependencies unchanged.

## Run

Use Python 3.12 and run these commands from the repository root:

```bash
python3.12 -m venv .venv-gui
source .venv-gui/bin/activate
python -m pip install -r desktop_gui/requirements.txt
python -m desktop_gui.main
```

On Windows PowerShell, activate with `.venv-gui\Scripts\Activate.ps1`.

The GUI talks to an authentication API at `http://127.0.0.1:8000` by default. To use another API origin:

```bash
PHISHREPORT_API_URL=https://api.example.test python -m desktop_gui.main
```

Use an HTTPS API outside local development. To open the password-reset screen while developing, provide the token from the reset email:

```bash
python -m desktop_gui.main --reset-token "token-from-email"
```

### Try the GUI with the static demo API

In a second terminal, start the development-only mock API:

```bash
python -m desktop_gui.mock_auth_api
```

Then launch the GUI using the run commands above. Sign in with
`demo@phishreport.test` / `phishreport-demo`. The API returns a fixed demo user
(`demo-user-001`, `Demo Analyst`); registration and password-reset responses
are simulated and do not create accounts, send email, or change passwords.
This server is for local UI development only, not production or real user data.

## Run in Docker with a native window (macOS and Windows)

For a step-by-step guide covering native and browser modes, see the
[GUI run guide](./GUI_RUN_GUIDE.html).

The GUI runs inside Docker but renders its Qt window to an X server on your
host. Install and start an X server before launching:

- **macOS:** Install and start [XQuartz](https://www.xquartz.org/), enable
  **Authenticate connections** and **Allow connections from network clients**
  in XQuartz Settings → Security, then quit and restart XQuartz. This enables
  its authenticated TCP X11 listener; display `:0` uses TCP port `6000`. The
  runner passes a temporary Xauthority cookie to the GUI container and removes
  it after exit. Keep access restricted to trusted local clients; do not use
  a blanket `xhost +` rule.
- **Windows:** Install and start [VcXsrv](https://sourceforge.net/projects/vcxsrv/)
  on display `0`. Allow it through Windows Firewall only on private networks.
  VcXsrv may need access control disabled for Docker Desktop; use this only on
  a trusted network and close VcXsrv after testing.

Run from the repository root in macOS/Linux Bash, Windows Git Bash, or WSL:

```bash
bash run.sh gui
```

The runner builds the GUI image and starts the development-only mock auth API
on a temporary private Docker network. The API is not published on a host
port; the runner removes the network and API container when the GUI exits.
The PySide app opens in a native X11 window. Sign in with
`demo@phishreport.test` / `phishreport-demo`. No Python installation or API
key is needed on the host, but Docker must be running.

The display defaults to `host.docker.internal:0`. Set
`PHISHREPORT_DISPLAY` if your host X server uses another address, and set
`PHISHREPORT_API_URL` to use a different authentication backend.

### Troubleshooting native display on macOS

If Qt reports `could not connect to display host.docker.internal:0`, check
that XQuartz is listening on port 6000:

```bash
nc -vz 127.0.0.1 6000
```

Then check the same connection from Docker:

```bash
docker run --rm phishreport-gui-native python -c \
  'import socket; socket.create_connection(("host.docker.internal", 6000), 3); print("XQuartz reachable from Docker")'
```

If the host check fails, enable **Allow connections from network clients** in
XQuartz Settings → Security, then quit and restart XQuartz. If the Docker
check fails, check macOS firewall settings and confirm Docker Desktop is
running. The runner automatically creates a mode-600 temporary Xauthority
file from the cookie for your current XQuartz display, mounts it read-only in
the GUI container, and removes it when the command exits. If authorization is
still rejected, enable **Authenticate connections** in the same XQuartz
settings panel and restart it. Do not work around this with unrestricted
`xhost +`. The `xcb-cursor0` text in Qt's error is a generic plugin hint; the
GUI image installs `libxcb-cursor0`, so check display connectivity and X11
authorization first.

If you prefer not to install a host X server, use the browser-streamed fallback:

```bash
bash run.sh gui-web
```

Open `http://localhost:6080/vnc.html?autoconnect=true&resize=scale`. This
noVNC port is bound to `127.0.0.1`; do not expose it publicly.

The regular image remains the default Docker build target and still starts the CLI. The Docker GUI target is optional, and the CLI's image does not install PySide6 or X11 packages.

## Tests

With the GUI dependency installed, run the focused desktop tests and existing project suite:

```bash
python -m pytest tests/test_desktop_auth_api.py tests/test_desktop_gui.py tests/test_desktop_docker.py -q
python -m pytest tests/test_desktop_mock_auth_api.py -q
python -m pytest
```

The GUI test module is skipped when PySide6 is not installed, so the existing CLI-only test environment remains unchanged.

## Scope

This phase implements authentication screens and an empty signed-in dashboard shell. The initials-based profile avatar opens a menu with a locked Settings screen and Sign out. Email analysis, reports, and other core features remain out of scope. See [BACKEND_HANDOFF.md](./BACKEND_HANDOFF.md) ([HTML](./BACKEND_HANDOFF.html)) for the authentication contract and proposed assessment/history API needs, and [FRONTEND_HANDOFF.md](./FRONTEND_HANDOFF.md) ([HTML](./FRONTEND_HANDOFF.html)) for the agreed UI/UX direction and GUI acceptance criteria.
