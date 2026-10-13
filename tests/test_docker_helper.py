"""Exercise the Bash launcher without requiring a Docker daemon in the test suite."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Bash helper checks run on Linux/Docker")


@pytest.fixture
def project(tmp_path):
    source = Path(__file__).resolve().parents[1]
    folder = tmp_path / "Project with spaces"
    folder.mkdir()
    shutil.copyfile(source / "docker.sh", folder / "docker.sh")
    (folder / ".env").write_text("GROQ_API_KEY=unused-offline\n", encoding="utf-8")
    emails = folder / "emails"
    emails.mkdir()
    shutil.copyfile(source / "emails" / "sample-1.eml", emails / "sample-1.eml")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    stub = binaries / "docker"
    stub.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "with open(os.environ['DOCKER_CALLS'], 'a', encoding='utf-8') as stream:\n"
        "    stream.write(json.dumps(sys.argv[1:]) + '\\n')\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return folder, binaries, tmp_path / "docker-calls.jsonl"


def launch(project, command="run", **settings):
    folder, binaries, calls = project
    environment = {**os.environ, "PATH": str(binaries) + os.pathsep + os.environ["PATH"]}
    environment.pop("PHISHREPORT_EMAIL_DIR", None)
    environment.update(settings)
    environment["DOCKER_CALLS"] = str(calls)
    result = subprocess.run(
        ["bash", str(folder / "docker.sh"), command],
        cwd=folder.parent,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    recorded = (
        [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
    )
    return result, recorded


def test_run_preserves_existing_data_and_mounts_its_directory(project):
    folder, _, _ = project
    # A real source message supplies legacy content; setup must copy bytes, not reinterpret it.
    message = (folder / "emails" / "sample-1.eml").read_text(encoding="utf-8")
    reports = json.dumps([{"message": message}], ensure_ascii=False).encode("utf-8")
    settings = b'{"eml_folder":"/emails","other_setting":true}'
    (folder / "reports.json").write_bytes(reports)
    (folder / ".phishreport_config.json").write_bytes(settings)
    (folder / "logs").mkdir()
    (folder / "logs" / "previous.log").write_text("Previous diagnostic", encoding="utf-8")

    result, calls = launch(project)

    assert result.returncode == 0, result.stderr
    data = folder / ".phishreport-data"
    assert (data / "reports.json").read_bytes() == reports
    assert (data / ".phishreport_config.json").read_bytes() == settings
    assert (data / "logs" / "previous.log").read_text() == "Previous diagnostic"
    assert (folder / "reports.json").read_bytes() == reports
    args = calls[-1]
    assert str(data) + ":/data" in args
    assert str(folder / "emails") + ":/emails:ro" in args
    assert args[args.index("-w") + 1] == "/data"
    assert args[-2:] == ["python", "/app/app/main.py"]
    assert "127.0.0.1:8000:8000" in args
    assert not any(":/app/reports.json" in arg for arg in args)


def test_later_run_does_not_replace_newer_container_history(project):
    folder, _, _ = project
    (folder / "reports.json").write_bytes(b"[]")
    assert launch(project)[0].returncode == 0
    data = folder / ".phishreport-data"
    newer = b'[{"priority":"MEDIUM","score":45}]'
    (data / "reports.json").write_bytes(newer)
    (data / ".phishreport_config.json").write_bytes(b'{"eml_folder":"/emails"}')
    result, _ = launch(project)
    assert result.returncode == 0, result.stderr
    assert (data / "reports.json").read_bytes() == newer
    assert (data / ".phishreport_config.json").read_bytes() == b'{"eml_folder":"/emails"}'


@pytest.mark.parametrize("name", ["reports.json", ".phishreport_config.json"])
def test_reject_directory_in_place_of_a_legacy_file(project, name):
    folder, _, _ = project
    (folder / name).mkdir()
    result, calls = launch(project)
    assert result.returncode != 0
    assert calls == []


def test_corrupt_existing_history_is_not_reset_by_setup(project):
    folder, _, _ = project
    (folder / "reports.json").write_bytes(b"{corrupt")
    result, _ = launch(project)
    assert result.returncode == 0, result.stderr
    assert (folder / ".phishreport-data" / "reports.json").read_bytes() == b"{corrupt"


def test_custom_email_directory_is_relative_to_project(project):
    folder, _, _ = project
    custom = folder / "Saved emails"
    custom.mkdir()
    shutil.copyfile(folder / "emails" / "sample-1.eml", custom / "sample-1.eml")
    result, calls = launch(project, PHISHREPORT_EMAIL_DIR="Saved emails")
    assert result.returncode == 0, result.stderr
    assert str(custom) + ":/emails:ro" in calls[-1]


def test_missing_email_directory_fails_before_starting_container(project):
    result, calls = launch(project, PHISHREPORT_EMAIL_DIR="missing emails")
    assert result.returncode != 0
    assert calls == []


def test_build_from_another_directory_uses_project_context(project):
    folder, _, _ = project
    result, calls = launch(project, command="build")
    assert result.returncode == 0, result.stderr
    assert calls[-1] == ["build", "-t", "phishreport", str(folder)]


def test_helper_has_unix_line_endings():
    assert b"\r\n" not in (Path(__file__).resolve().parents[1] / "docker.sh").read_bytes()
