from pathlib import Path

import pytest

from app_gui.docker_entrypoint import _validate_display_size


def test_dockerfile_defines_native_x11_gui_target():
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()
    assert "FROM base AS gui-native" in dockerfile
    assert "ENV DISPLAY=host.docker.internal:0" in dockerfile
    assert 'CMD ["python", "-m", "app_gui.main"]' in dockerfile


def test_dockerfile_keeps_novnc_gui_target():
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()
    assert "FROM gui-native AS gui" in dockerfile
    assert "EXPOSE 6080" in dockerfile
    assert 'CMD ["python", "-m", "app_gui.docker_entrypoint"]' in dockerfile


def test_gui_dependency_uses_the_single_root_requirements_file():
    root = Path(__file__).resolve().parents[1]
    requirements = (root / "requirements.txt").read_text()

    assert "PySide6-Essentials==6.10.2" in requirements
    assert not (root / "app_gui" / "requirements.txt").exists()
    assert "COPY requirements.txt ." in (root / "Dockerfile").read_text()


@pytest.mark.parametrize(
    "size",
    ["800x600x16", "1440x900x24", "3840x2160x32"],
)
def test_validate_supported_display_size(size):
    assert _validate_display_size(size) == size


@pytest.mark.parametrize(
    "size",
    ["800x600", "abcx900x24", "799x600x24", "3841x2160x24", "1440x900x8"],
)
def test_validate_rejects_unsupported_display_size(size):
    with pytest.raises(ValueError):
        _validate_display_size(size)
