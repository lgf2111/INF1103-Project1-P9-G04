"""Each domain class returns what the free function it replaced returned."""

import io
import logging

import pytest

from phishreport.data import DataManager, JsonReportStorage, SqliteReportStorage
from phishreport.data.migration import StorageMigration
from phishreport.data.repair import HistoryRepair
from phishreport.data.storage import RevisionPolicy
from phishreport.io.command_catalog import CommandCapabilities, CommandCatalog
from phishreport.io.record_builder import InputDeriver
from phishreport.io.report_csv import CSV_COLUMNS, ReportCsv
from phishreport.logging_setup import SecretRedactingFilter, SecretRedactor


def test_input_deriver_derives_the_same_record_fields():
    text = (
        "From: Bank <help@example.com>\n\n"
        "Open https://example.com/login. Attached: invoice.pdf"
    )
    assert InputDeriver.derive_inputs(text) == {
        "channel": "email",
        "sender": "help@example.com",
        "has_link": True,
        "link": "https://example.com/login",
        "has_file": True,
        "file_name": "invoice.pdf",
    }
    assert InputDeriver.derive_inputs("Call +65 9123 4567 now.")["channel"] == "sms"
    assert InputDeriver.derive_inputs("Meet me at the usual place.") == {
        "channel": "chat",
        "sender": None,
        "has_link": False,
        "link": None,
        "has_file": False,
        "file_name": None,
    }


def test_input_deriver_helpers_keep_their_individual_contracts():
    assert InputDeriver.extract_link("see (https://example.com/a).") == "https://example.com/a"
    assert InputDeriver.extract_sender("write to a@b.co or +6591234567") == "a@b.co"
    assert InputDeriver.extract_sender("ring +65 9123 4567") == "+65 9123 4567"
    assert InputDeriver.detect_channel("code 123456") == "sms"
    assert InputDeriver.extract_file("see attachment") == (True, None)
    assert InputDeriver.extract_file("nothing here") == (False, None)


def report(assessment_id, score):
    return {"assessment_id": assessment_id, "result": {"score": score}}


def test_revision_policy_replaces_the_last_copy_and_appends_unmatched_records():
    stored = [report("a", 1), report("b", 2), report("a", 3)]

    assert RevisionPolicy.replace_revision(stored, report("a", 9)) == [
        report("b", 2),
        report("a", 9),
    ]
    assert RevisionPolicy.replace_revision(stored, report("c", 5)) == [*stored, report("c", 5)]
    assert RevisionPolicy.replace_revision(stored, {"message": "no id"}) == [
        *stored,
        {"message": "no id"},
    ]


def test_revision_policy_keeps_the_last_copy_and_counts_the_rest():
    anonymous = {"message": "no id"}
    stored = [report("a", 1), anonymous, report("b", 2), report("a", 3), anonymous]

    assert RevisionPolicy.keep_last_revision(stored) == (
        [anonymous, report("b", 2), report("a", 3), anonymous],
        1,
    )


def test_report_csv_writes_the_same_bytes_to_memory_and_to_a_file(tmp_path):
    records = [
        {"assessment_id": "id-1", "channel": "chat", "message": "=1+1",
         "result": {"score": 95, "priority": "HIGH"}},
        {"message": "plain"},
    ]
    expected = (
        "assessment_id,channel,priority,score,message\r\n"
        "id-1,chat,HIGH,95,'=1+1\r\n"
        ",,,,plain\r\n"
    )

    stream = io.StringIO(newline="")
    ReportCsv.write(stream, records)
    destination = tmp_path / "out.csv"
    ReportCsv.export(destination, records)

    assert stream.getvalue() == expected
    assert ReportCsv.to_bytes(records) == expected.encode("utf-8")
    assert destination.read_bytes() == expected.encode("utf-8")
    assert expected.splitlines()[0].split(",") == list(CSV_COLUMNS)


def test_history_repair_drops_duplicates_and_reports_the_count(tmp_path):
    storage = JsonReportStorage(tmp_path / "reports.json")
    manager = DataManager(storage=storage)
    storage.write_records([report("a", 1), report("b", 2), report("a", 3)])

    assert HistoryRepair.repair_history(manager) == 1
    assert HistoryRepair.repair_history(manager) == 0
    assert storage.read_records() == [report("b", 2), report("a", 3)]


def test_storage_migration_copies_json_history_into_sqlite(tmp_path):
    source = tmp_path / "reports.json"
    target = tmp_path / "reports.sqlite3"
    source.write_text('[{"a": 1}, {"b": 2}]', encoding="utf-8")

    assert StorageMigration.migrate(source, target) == 2
    assert StorageMigration.migrate(source, target) == 0
    assert SqliteReportStorage(target).read_records() == [{"a": 1}, {"b": 2}]


def test_command_catalog_discovers_the_shipped_commands_in_name_order():
    capabilities = CommandCapabilities(
        prepare_record=lambda request: {},
        assess_record=lambda record: {},
        session_status=lambda request: "",
        report_count=lambda: 0,
    )

    names = [command.name for command in CommandCatalog.discover_commands(capabilities)]

    assert names == sorted(names)
    assert {"check", "help", "status"} <= set(names)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("url bot123456789:AAFakeSyntheticTokenForTests/getMe",
         "url bot<redacted>/getMe"),
        ("token=abcdef&x=1", "token=<redacted>&x=1"),
        ("Authorization: Bearer abc.def", "Authorization: Bearer <redacted>"),
        ("key gsk_AbC123_x", "key <redacted>"),
        ("nothing secret", "nothing secret"),
    ],
)
def test_secret_redactor_masks_what_the_function_masked(message, expected):
    assert SecretRedactor().redact_secrets(message) == expected


def test_log_filter_redacts_through_its_redactor_instance():
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "password=%s", ("hunter2",), None)

    assert SecretRedactingFilter(SecretRedactor()).filter(record) is True
    assert record.getMessage() == "password=<redacted>"
