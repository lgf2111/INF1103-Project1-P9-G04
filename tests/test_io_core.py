from pathlib import Path


def test_eml_reader_decodes_fixture_from_bytes_and_path():
    from io_core import EmlReader

    path = Path(__file__).resolve().parent / "fixtures" / "sample-1.eml"
    reader = EmlReader()

    sender, message = reader.read_bytes(path.read_bytes())

    assert sender
    assert message.startswith("Subject: ")
    assert reader.read_path(path) == (sender, message)
