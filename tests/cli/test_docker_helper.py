"""run.sh Docker helper behavior."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REAL_EMAILS = Path(__file__).resolve().parents[1] / "fixtures"


# ============================================================================
# Docker Helper
# ============================================================================
@pytest.fixture
def docker_helper_project(tmp_path):
    source = Path(__file__).resolve().parents[2]
    folder = tmp_path / "Project with spaces"
    folder.mkdir()
    shutil.copyfile(source / "run.sh", folder / "run.sh")
    (folder / ".env").write_text("GROQ_API_KEY=unused-offline\n", encoding="utf-8")
    emails = folder / "emails"
    emails.mkdir()
    shutil.copyfile(source / "tests" / "fixtures" / "sample-1.eml", emails / "sample-1.eml")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    stub = binaries / "docker"
    stub.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "if (\n"
        "    sys.argv[1:3] == ['image', 'inspect']\n"
        "    and os.environ.get('DOCKER_IMAGE_MISSING') == '1'\n"
        "):\n"
        "    raise SystemExit(1)\n"
        "with open(os.environ['DOCKER_CALLS'], 'a', encoding='utf-8') as stream:\n"
        "    stream.write(json.dumps(sys.argv[1:]) + '\\n')\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return folder, binaries, tmp_path / "docker-calls.jsonl"


def docker_helper_launch(docker_helper_project, command="run", **settings):
    folder, binaries, calls = docker_helper_project
    environment = {**os.environ, "PATH": str(binaries) + os.pathsep + os.environ["PATH"]}
    environment.pop("PHISHREPORT_EMAIL_DIR", None)
    environment.update(settings)
    environment["DOCKER_CALLS"] = str(calls)
    result = subprocess.run(
        ["bash", str(folder / "run.sh"), command],
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


@pytest.mark.skipif(os.name != "posix", reason="Bash helper checks run on Linux/Docker")
def test_docker_helper_run_preserves_existing_data_and_mounts_its_directory(docker_helper_project):
    folder, _, _ = docker_helper_project
    # A real source message supplies legacy content; setup must copy bytes, not reinterpret it.
    message = (folder / "emails" / "sample-1.eml").read_text(encoding="utf-8")
    reports = json.dumps([{"message": message}], ensure_ascii=False).encode("utf-8")
    settings = b'{"eml_folder":"/emails","other_setting":true}'
    (folder / "reports.json").write_bytes(reports)
    (folder / ".phishreport_config.json").write_bytes(settings)
    (folder / "logs").mkdir()
    (folder / "logs" / "previous.log").write_text("Previous diagnostic", encoding="utf-8")

    result, calls = docker_helper_launch(docker_helper_project)

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
    assert args[-3:] == ["python", "-m", "phishreport.cli"]
    assert "127.0.0.1:8000:8000" in args
    assert not any(":/phishreport/reports.json" in arg for arg in args)


@pytest.mark.skipif(os.name != "posix", reason="Bash helper checks run on Linux/Docker")
def test_docker_helper_later_run_does_not_replace_newer_container_history(docker_helper_project):
    folder, _, _ = docker_helper_project
    (folder / "reports.json").write_bytes(b"[]")
    assert docker_helper_launch(docker_helper_project)[0].returncode == 0
    data = folder / ".phishreport-data"
    newer = b'[{"priority":"MEDIUM","score":45}]'
    (data / "reports.json").write_bytes(newer)
    (data / ".phishreport_config.json").write_bytes(b'{"eml_folder":"/emails"}')
    result, _ = docker_helper_launch(docker_helper_project)
    assert result.returncode == 0, result.stderr
    assert (data / "reports.json").read_bytes() == newer
    assert (data / ".phishreport_config.json").read_bytes() == b'{"eml_folder":"/emails"}'


@pytest.mark.skipif(os.name != "posix", reason="Bash helper checks run on Linux/Docker")
@pytest.mark.parametrize("name", ["reports.json", ".phishreport_config.json"])
def test_docker_helper_reject_directory_in_place_of_a_legacy_file(docker_helper_project, name):
    folder, _, _ = docker_helper_project
    (folder / name).mkdir()
    result, calls = docker_helper_launch(docker_helper_project)
    assert result.returncode != 0
    assert calls == []


@pytest.mark.skipif(os.name != "posix", reason="Bash helper checks run on Linux/Docker")
def test_docker_helper_corrupt_existing_history_is_not_reset_by_setup(docker_helper_project):
    folder, _, _ = docker_helper_project
    (folder / "reports.json").write_bytes(b"{corrupt")
    result, _ = docker_helper_launch(docker_helper_project)
    assert result.returncode == 0, result.stderr
    assert (folder / ".phishreport-data" / "reports.json").read_bytes() == b"{corrupt"


@pytest.mark.skipif(os.name != "posix", reason="Bash helper checks run on Linux/Docker")
def test_docker_helper_custom_email_directory_is_relative_to_project(docker_helper_project):
    folder, _, _ = docker_helper_project
    custom = folder / "Saved emails"
    custom.mkdir()
    shutil.copyfile(folder / "emails" / "sample-1.eml", custom / "sample-1.eml")
    result, calls = docker_helper_launch(
        docker_helper_project, PHISHREPORT_EMAIL_DIR="Saved emails"
    )
    assert result.returncode == 0, result.stderr
    assert str(custom) + ":/emails:ro" in calls[-1]


@pytest.mark.skipif(os.name != "posix", reason="Bash helper checks run on Linux/Docker")
def test_docker_helper_missing_email_directory_fails_before_starting_container(
    docker_helper_project,
):
    result, calls = docker_helper_launch(
        docker_helper_project, PHISHREPORT_EMAIL_DIR="missing emails"
    )
    assert result.returncode != 0
    assert calls == []


@pytest.mark.skipif(os.name != "posix", reason="Bash helper checks run on Linux/Docker")
def test_docker_helper_build_from_another_directory_uses_project_context(docker_helper_project):
    folder, _, _ = docker_helper_project
    result, calls = docker_helper_launch(docker_helper_project, command="build")
    assert result.returncode == 0, result.stderr
    assert calls[-1] == ["build", "-t", "phishreport", str(folder)]


@pytest.mark.skipif(os.name != "posix", reason="Bash helper checks run on Linux/Docker")
def test_docker_helper_run_builds_image_when_missing(docker_helper_project):
    result, calls = docker_helper_launch(docker_helper_project, DOCKER_IMAGE_MISSING="1")
    assert result.returncode == 0, result.stderr
    assert ["build", "-t", "phishreport", str(docker_helper_project[0])] in calls
    assert calls[-1][-3:] == ["python", "-m", "phishreport.cli"]


@pytest.mark.skipif(os.name != "posix", reason="Bash helper checks run on Linux/Docker")
def test_docker_helper_helper_has_unix_line_endings():
    assert b"\r\n" not in (Path(__file__).resolve().parents[2] / "run.sh").read_bytes()


@pytest.mark.skipif(os.name != "posix", reason="Bash helper checks run on Linux/Docker")
def test_docker_helper_telegram_mounts_history_read_only(docker_helper_project):
    folder, _, _ = docker_helper_project
    config = folder / ".env"
    with config.open("a", encoding="utf-8") as stream:
        stream.write("TELEGRAM_BOT_TOKEN=unused-offline\nTELEGRAM_ALLOWED_CHAT_ID=12345\n")

    result, calls = docker_helper_launch(
        docker_helper_project, command="telegram", DOCKER_IMAGE_MISSING="1"
    )

    assert result.returncode == 0, result.stderr
    assert ["build", "--target", "telegram", "-t", "phishreport-telegram", str(folder)] in calls
    data = folder / ".phishreport-data"
    assert calls[-1] == [
        "run", "--rm", "--env-file", str(config), "-v", str(data) + ":/data:ro",
        "phishreport-telegram",
    ]
    assert list(data.iterdir()) == []


@pytest.mark.skipif(os.name != "posix", reason="Bash helper checks run on Linux/Docker")
def test_docker_helper_creates_default_import_folder_on_clean_checkout(docker_helper_project):
    folder, _, _ = docker_helper_project
    shutil.rmtree(folder / "emails")  # This fixture owns an isolated temporary project.
    result, calls = docker_helper_launch(docker_helper_project)
    assert result.returncode == 0, result.stderr
    assert (folder / "emails").is_dir()
    assert list((folder / "emails").iterdir()) == []
    assert str(folder / "emails") + ":/emails:ro" in calls[-1]
