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

## Run in Docker Desktop (macOS and Windows)

Docker containers cannot open a Linux Qt window directly on the macOS or Windows desktop. The GUI Docker target runs the same PySide6 app in a virtual display and exposes its window through noVNC, which you open in a local browser. No host X server is needed.

Build and run:

```bash
docker build --target gui -t phishreport-gui .
docker run --rm -it \
  -p 127.0.0.1:6080:6080 \
  -e PHISHREPORT_API_URL=http://host.docker.internal:8000 \
  phishreport-gui
```

Then open `http://localhost:6080/vnc.html?autoconnect=true&resize=scale`. This works with Docker Desktop on macOS and Windows. `host.docker.internal` lets the container reach an API running on the host. Override `PHISHREPORT_API_URL` if the backend is elsewhere. Keep the port bound to `127.0.0.1`; the noVNC session has no separate password.

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

This phase implements authentication screens and an empty signed-in dashboard shell. The initials-based profile avatar opens a menu with a locked Settings screen and Sign out. Email analysis, reports, and other core features remain out of scope. See [BACKEND_HANDOFF.md](./BACKEND_HANDOFF.md) for the API contract.
