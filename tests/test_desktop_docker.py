import pytest

from desktop_gui.docker_entrypoint import _validate_display_size


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
