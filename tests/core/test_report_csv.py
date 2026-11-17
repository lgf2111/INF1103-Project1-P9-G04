"""Report CSV contract and failure behavior."""

import csv

import pytest

from phishreport.io.report_csv import ReportCsv, ReportExportError


def _read_csv(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.reader(stream))


def test_csv_preserves_order_values_and_escaping(tmp_path):
    destination = tmp_path / "history.csv"
    first = 'Phishing sample, "quoted"\r\n\u9493\u9c7c'
    records = [
        {"assessment_id": "saved-1", "channel": "chat", "message": first,
         "result": {"score": 95, "priority": "HIGH"}},
        {"channel": "email", "score": 0, "priority": "low", "message": "Legacy"},
        {"message": "No saved assessment"},
    ]

    ReportCsv.export(destination, records)

    assert _read_csv(destination) == [
        ["assessment_id", "channel", "priority", "score", "message"],
        ["saved-1", "chat", "HIGH", "95", first],
        ["", "email", "low", "0", "Legacy"],
        ["", "", "", "", "No saved assessment"],
    ]


@pytest.mark.parametrize("value", [
    '=1+1",=2+2', "  +123", "-A1", "@SUM(A1)", "\ttext", "\rtext", "\ntext",
    "\uff1d1+1", "\uff0b1", "\uff0d1", "\uff20A1",
])
def test_csv_treats_formula_like_strings_as_text(tmp_path, value):
    destination = tmp_path / "history.csv"

    ReportCsv.export(destination, [
        {"assessment_id": value, "channel": value, "priority": value, "message": value},
    ])

    escaped = "'" + value
    assert _read_csv(destination)[1:] == [[escaped, escaped, escaped, "", escaped]]


def test_csv_empty_iterable_writes_header_only(tmp_path):
    destination = tmp_path / "history.csv"

    ReportCsv.export(destination, [])

    assert _read_csv(destination) == [["assessment_id", "channel", "priority", "score", "message"]]


def test_csv_write_failure_preserves_an_existing_destination(tmp_path):
    destination = tmp_path / "history.csv"
    destination.write_bytes(b"existing contents")

    with pytest.raises(ReportExportError):
        ReportCsv.export(destination, [])

    assert destination.read_bytes() == b"existing contents"


def test_csv_incomplete_new_file_is_removed_and_can_be_retried(tmp_path):
    destination = tmp_path / "history.csv"

    with pytest.raises(ReportExportError):
        ReportCsv.export(destination, [{"message": "Valid row"}, {"message": "\ud800"}])

    assert not destination.exists()
    ReportCsv.export(destination, [])
    assert destination.is_file()
