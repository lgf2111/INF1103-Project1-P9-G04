"""Schema contracts for the independent data-layer objects."""

from copy import deepcopy
from importlib import import_module

import pytest

from phishreport.data import JsonReportStorage, SqliteReportStorage


def validator():
    """Resolve the new API at test time so missing implementation fails tests."""
    return import_module("phishreport.data.validator").ReportValidator()


def v2_report():
    return {
        "schema_version": 2,
        "channel": "email",
        "message": "  Original message\n",
        "result": {"score": 0, "priority": "LOW", "reasons": [], "checklist": []},
    }


def v3_report():
    return {
        "schema_version": 3,
        "channel": " telegram ",
        "message": "  Original message\n",
        "sender": " @original ",
        "has_link": True,
        "link": " https://example.test/path ",
        "has_file": True,
        "file_name": " notice.pdf ",
        "exposure": {
            "clicked": None,
            "downloaded": None,
            "submitted_category": None,
            "disclosure_answered": False,
        },
        "result": {"score": 0, "priority": "LOW", "reasons": [], "checklist": []},
    }


@pytest.mark.parametrize(
    "clicked,downloaded,category,answered",
    [
        (None, None, None, False),
        (False, False, None, True),
        (True, None, None, False),
        (None, False, None, True),
        (False, True, "password", True),
        (None, None, "otp", True),
    ],
    ids=["unknown", "confirmed-no", "partial-clicked", "partial-downloaded", "password", "otp"],
)
def test_v3_preserves_nullable_exposure_and_original_record(
    clicked, downloaded, category, answered
):
    record = v3_report()
    record["exposure"] = {
        "clicked": clicked,
        "downloaded": downloaded,
        "submitted_category": category,
        "disclosure_answered": answered,
    }
    before = deepcopy(record)
    assert validator()._validate_v3(record) is record
    assert record == before


@pytest.mark.parametrize(
    "metadata",
    [
        {"sender": None, "has_link": False, "link": None, "has_file": False, "file_name": None},
        {"sender": "", "has_file": True, "file_name": None},
    ],
    ids=["no-metadata", "generic-attachment-blank-sender"],
)
def test_v3_accepts_absent_metadata_and_generic_attachment(metadata):
    record = v3_report()
    record.update(metadata)
    before = deepcopy(record)
    assert validator()._validate_v3(record) is record
    assert record == before


@pytest.mark.parametrize("record", [None, [], "report"])
def test_v3_rejects_nonobject_records(record):
    before = deepcopy(record)
    with pytest.raises(ValueError):
        validator()._validate_v3(record)
    assert record == before


@pytest.mark.parametrize("section", [None, "exposure", "result"])
@pytest.mark.parametrize("extra", [False, True], ids=["missing", "extra"])
def test_v3_requires_exact_fields(section, extra):
    record = v3_report()
    fields = record if section is None else record[section]
    if extra:
        fields["unknown"] = None
    else:
        del fields[next(iter(fields))]
    before = deepcopy(record)
    with pytest.raises(ValueError):
        validator()._validate_v3(record)
    assert record == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True), ("schema_version", 3.0), ("schema_version", "3"),
        ("schema_version", 2),
        ("channel", " \n"), ("channel", None), ("message", "\t"), ("message", 1),
        ("sender", 1), ("link", " "), ("link", 1),
        ("file_name", "\t"), ("file_name", []),
        ("has_link", 1), ("has_file", 0), ("has_file", None),
        ("exposure", []), ("exposure", None), ("result", []),
        ("has_link", False), ("link", None), ("has_file", False),
    ],
)
def test_v3_rejects_invalid_root_fields_without_mutation(field, value):
    record = v3_report()
    record[field] = value
    before = deepcopy(record)
    with pytest.raises(ValueError):
        validator()._validate_v3(record)
    assert record == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("clicked", 1), ("downloaded", 0), ("clicked", "yes"),
        ("disclosure_answered", 1), ("disclosure_answered", None),
        ("submitted_category", "other"), ("submitted_category", True),
        ("submitted_category", []), ("submitted_category", "password"),
        ("submitted_category", "otp"),
    ],
)
def test_v3_rejects_invalid_or_unanswered_disclosure_without_mutation(field, value):
    record = v3_report()
    record["exposure"][field] = value
    before = deepcopy(record)
    with pytest.raises(ValueError):
        validator()._validate_v3(record)
    assert record == before


@pytest.mark.parametrize(
    "field,value",
    [("score", True), ("score", 101), ("priority", "other"),
     ("reasons", [" "]), ("checklist", "text")],
)
def test_v3_rejects_invalid_assessment_without_mutation(field, value):
    record = v3_report()
    record["result"][field] = value
    before = deepcopy(record)
    with pytest.raises(ValueError):
        validator()._validate_v3(record)
    assert record == before


def v1_report():
    return {
        "schema_version": 1,
        "channel": "",
        "sender": None,
        "message": " Original message ",
        "has_link": False,
        "link": None,
        "has_file": False,
        "file_name": None,
        "clicked": False,
        "downloaded": False,
        "submitted_category": None,
        "ai": {
            "credential_request": False,
            "suspicious": False,
            "insufficient_context": True,
            "details": {"emails": [], "phone_numbers": [], "ip_addresses": []},
        },
        "result": {"score": 100, "priority": "HIGH", "reasons": [], "checklist": []},
    }


def summary_report():
    return {
        "channel": "",
        "sender": None,
        "message": " Original ",
        "link": None,
        "file_name": None,
        "details": {"emails": [], "phone_numbers": [], "ip_addresses": []},
        "score": 50,
        "priority": "MEDIUM",
    }


@pytest.mark.parametrize("method", ["validate_new", "validate_stored"])
def test_v2_returns_original_without_normalizing(method):
    record = v2_report()
    before = deepcopy(record)
    assert getattr(validator(), method)(record) is record
    assert record == before


@pytest.mark.parametrize(
    "record",
    [
        v1_report(),
        summary_report(),
        {},
        {
            "message": "",
            "score": -2.5,
            "priority": "unknown",
            "reasons": [""],
            "result": {"score": 200, "checklist": [""]},
            "unknown": {"retained": True},
        },
    ],
)
def test_stored_historical_records_keep_missing_and_unknown_fields(record):
    before = deepcopy(record)
    assert validator().validate_stored(record) is record
    assert record == before
    with pytest.raises(ValueError):
        validator().validate_new(record)
    assert record == before


@pytest.mark.parametrize("version", [True, False, 2.0, "2", None, 0, 3])
@pytest.mark.parametrize("method", ["validate_new", "validate_stored"])
def test_unsupported_or_noninteger_schema_versions(version, method):
    record = v2_report()
    record["schema_version"] = version
    with pytest.raises(ValueError):
        getattr(validator(), method)(record)


@pytest.mark.parametrize("field", ["schema_version", "channel", "message", "result", "extra"])
def test_new_v2_requires_exact_fields(field):
    record = v2_report()
    if field == "extra":
        record[field] = "unrecognized"
    else:
        del record[field]
    with pytest.raises(ValueError):
        validator().validate_new(record)


@pytest.mark.parametrize(
    "field,value", [("channel", " \n"), ("message", "\t"), ("channel", None), ("message", 1)]
)
@pytest.mark.parametrize("method", ["validate_new", "validate_stored"])
def test_v2_rejects_blank_or_nonstrings_without_mutation(field, value, method):
    record = v2_report()
    record[field] = value
    before = deepcopy(record)
    with pytest.raises(ValueError):
        getattr(validator(), method)(record)
    assert record == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("score", True),
        ("score", False),
        ("score", 1.0),
        ("score", -1),
        ("score", 101),
        ("priority", "other"),
        ("reasons", [" "]),
        ("checklist", ["\t"]),
        ("reasons", "text"),
        ("checklist", [1]),
    ],
)
@pytest.mark.parametrize("factory", [v2_report, v1_report])
def test_versioned_assessment_rejects_invalid_values(factory, field, value):
    record = factory()
    record["result"][field] = value
    before = deepcopy(record)
    with pytest.raises(ValueError):
        validator().validate_stored(record)
    assert record == before


@pytest.mark.parametrize(
    "record",
    [
        None,
        [],
        1,
        "report",
        {"score": True},
        {"result": {"score": False}},
        {"score": float("inf")},
        {"has_link": 1},
        {"result": []},
        {"details": {"emails": [1]}},
        {"message": 1},
        {"checklist": None},
    ],
)
def test_invalid_stored_structures_raise_value_error(record):
    with pytest.raises(ValueError):
        validator().validate_stored(record)


@pytest.mark.parametrize("factory", [v1_report, summary_report])
def test_historical_extraction_rejects_blank_entries(factory):
    record = factory()
    details = record["ai"]["details"] if "ai" in record else record["details"]
    details["emails"] = [" "]
    with pytest.raises(ValueError):
        validator().validate_stored(record)


def test_v1_requires_complete_fields_and_boolean_findings():
    record = v1_report()
    del record["ai"]
    with pytest.raises(ValueError):
        validator().validate_stored(record)
    record = v1_report()
    record["ai"]["suspicious"] = 1
    with pytest.raises(ValueError):
        validator().validate_stored(record)


def json_storage(path):
    return import_module("phishreport.data.json_storage").JsonReportStorage(path)


@pytest.fixture(params=[JsonReportStorage, SqliteReportStorage], ids=["json", "sqlite"])
def storage(request, tmp_path):
    suffix = ".json" if request.param is JsonReportStorage else ".sqlite3"
    return request.param(tmp_path / ("reports" + suffix))


def test_storage_contract_round_trip_replacement_and_order(storage):
    assert storage.read_records() == []
    records = [v2_report(), v1_report(), summary_report(), {}, {"unknown": "保留"}]
    before = deepcopy(records)
    storage.write_records(records)
    assert records == before
    assert storage.read_records() == before
    storage.write_records([{}])
    assert storage.read_records() == [{}]
    storage.write_records([])
    assert storage.read_records() == []


def test_storage_contract_nested_isolation(storage):
    records = [v2_report()]
    records[0]["result"]["checklist"] = ["Keep this"]
    before = deepcopy(records)
    storage.write_records(records)
    records[0]["result"]["checklist"][0] = "Changed input"
    records.append({})
    read = storage.read_records()
    assert read == before
    read[0]["result"]["checklist"].append("Changed read")
    read.clear()
    assert storage.read_records() == before


def test_storage_interface_is_abstract():
    with pytest.raises(TypeError):
        import_module("phishreport.data.storage").ReportStorage()


@pytest.mark.parametrize(
    "content",
    [
        b'[{"message":"first","message":"second"}]',
        b'[{"nested":{"a":1,"a":2}}]',
        b'[{"score":NaN}]', b'[{"score":Infinity}]', b'[{"score":-Infinity}]',
        b'[{"message":"\xff"}]', b'{' , b'{}', b'null', b'[1]', b'[{},null]',
        pytest.param(b'[' * 2000 + b']' * 2000, id="deep-json"),
    ],
)
def test_json_rejects_malformed_containers_without_changing_bytes(tmp_path, content):
    path = tmp_path / "reports.json"
    path.write_bytes(content)
    with pytest.raises(ValueError):
        json_storage(path).read_records()
    assert path.read_bytes() == content


def test_json_read_permission_error_propagates(tmp_path, monkeypatch):
    path = tmp_path / "reports.json"
    path.write_bytes(b"[{}]")
    backend = json_storage(path)
    error = PermissionError("read denied")

    def deny(*args, **kwargs):
        raise error

    with monkeypatch.context() as patch:
        patch.setattr("builtins.open", deny)
        with pytest.raises(PermissionError) as caught:
            backend.read_records()
    assert caught.value is error
    assert path.read_bytes() == b"[{}]"


@pytest.mark.parametrize("stage", ["dump", "flush", "fsync", "replace"])
def test_json_write_failure_preserves_bytes_and_cleans_temporary(tmp_path, monkeypatch, stage):
    path = tmp_path / "reports.json"
    path.write_bytes(b"[{}]\n")
    backend = json_storage(path)
    module = import_module("phishreport.data.json_storage")
    error = OSError("injected " + stage)

    def fail(*args, **kwargs):
        raise error

    if stage == "dump":
        monkeypatch.setattr(module.json, "dump", fail)
    elif stage == "flush":
        original = module.tempfile.NamedTemporaryFile

        def temporary(*args, **kwargs):
            stream = original(*args, **kwargs)
            stream.flush = fail
            return stream

        monkeypatch.setattr(module.tempfile, "NamedTemporaryFile", temporary)
    else:
        monkeypatch.setattr(module.os, stage, fail)
    with pytest.raises(OSError) as caught:
        backend.write_records([v2_report()])
    assert caught.value is error
    assert path.read_bytes() == b"[{}]\n"
    assert list(tmp_path.iterdir()) == [path]


def test_json_cleanup_failure_preserves_primary_exception(tmp_path, monkeypatch):
    path = tmp_path / "reports.json"
    path.write_bytes(b"[{}]")
    backend = json_storage(path)
    module = import_module("phishreport.data.json_storage")
    primary = ValueError("serialization failed")

    def fail_dump(*args, **kwargs):
        raise primary

    def fail_cleanup(*args, **kwargs):
        raise PermissionError("cleanup denied")

    with monkeypatch.context() as patch:
        patch.setattr(module.json, "dump", fail_dump)
        patch.setattr(module.os, "unlink", fail_cleanup)
        with pytest.raises(ValueError) as caught:
            backend.write_records([v2_report()])
    assert caught.value is primary
    assert "cleanup" in " ".join(caught.value.__notes__).lower()
    assert path.read_bytes() == b"[{}]"
    leftovers = [entry for entry in tmp_path.iterdir() if entry != path]
    assert len(leftovers) == 1
    leftovers[0].unlink()


def test_json_relative_path_uses_operation_directory(tmp_path, monkeypatch):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    monkeypatch.chdir(first)
    backend = json_storage("reports.json")
    monkeypatch.chdir(second)
    backend.write_records([{"message": "  保留\n"}])
    assert backend.read_records() == [{"message": "  保留\n"}]
    assert not (first / "reports.json").exists()
    monkeypatch.chdir(first)
    assert backend.read_records() == []


def test_json_does_not_create_parent_directories(tmp_path):
    parent = tmp_path / "absent"
    with pytest.raises(OSError):
        json_storage(parent / "reports.json").write_records([])
    assert not parent.exists()


def test_json_nonfinite_write_preserves_original(tmp_path):
    path = tmp_path / "reports.json"
    path.write_bytes(b"[{}]")
    with pytest.raises(ValueError):
        json_storage(path).write_records([{"score": float("nan")}])
    assert path.read_bytes() == b"[{}]"
    assert list(tmp_path.iterdir()) == [path]


def test_json_successful_replace_needs_no_cleanup(tmp_path, monkeypatch):
    path = tmp_path / "reports.json"
    backend = json_storage(path)
    module = import_module("phishreport.data.json_storage")

    def deny_cleanup(*args, **kwargs):
        raise PermissionError("cleanup denied")

    with monkeypatch.context() as patch:
        patch.setattr(module.os, "unlink", deny_cleanup)
        backend.write_records([{}])
    assert backend.read_records() == [{}]
    assert list(tmp_path.iterdir()) == [path]


def manager(storage=None, validator=None):
    return import_module("phishreport.data").DataManager(storage=storage, validator=validator)


def test_manager_saves_v2_and_appends_mixed_history_unchanged(storage):
    subject = manager(storage)
    record = v2_report()
    original = deepcopy(record)
    subject.save(record)
    assert subject.load(strict=True) == [original]
    history = [v1_report(), summary_report(), {}, {"unknown": "保留"}]
    storage.write_records(history)
    before = deepcopy(history)
    subject.save(record)
    assert subject.load(strict=True) == [*before, original]
    assert history == before
    assert record == original


@pytest.mark.parametrize("invalid", [{"schema_version": 3}, {"score": True}])
def test_manager_invalid_history_prevents_save_and_partial_load(storage, invalid):
    history = [v2_report(), invalid, {}]
    storage.write_records(history)
    subject = manager(storage)
    assert subject.load() == []
    with pytest.raises(ValueError):
        subject.save(v2_report())
    assert storage.read_records() == history


def test_manager_query_preserves_order_and_propagates_predicate_errors(storage):
    history = [{"message": "first"}, {}, {"message": "last"}]
    storage.write_records(history)
    subject = manager(storage)
    assert subject.query(lambda record: "message" in record) == [history[0], history[2]]
    error = RuntimeError("predicate failed")

    def fail(record):
        raise error

    with pytest.raises(RuntimeError) as caught:
        subject.query(fail)
    assert caught.value is error
    assert storage.read_records() == history


@pytest.fixture
def backend_spy():
    contract = import_module("phishreport.data.storage").ReportStorage

    class BackendSpy(contract):
        def __init__(self):
            self.records = []
            self.calls = []
            self.read_error = None
            self.write_error = None

        def __bool__(self):
            return False

        def read_records(self):
            self.calls.append("read")
            if self.read_error is not None:
                raise self.read_error
            return deepcopy(self.records)

        def write_records(self, records):
            self.calls.append("write")
            if self.write_error is not None:
                raise self.write_error
            self.records = deepcopy(records)

    return BackendSpy()


def test_manager_invalid_new_input_never_touches_storage(backend_spy):
    subject = manager(backend_spy)
    with pytest.raises(ValueError):
        subject.save(v1_report())
    assert backend_spy.calls == []


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("error", [ValueError("private data"), OSError("private path")])
@pytest.mark.parametrize("level", ["INFO", "DEBUG"])
def test_manager_read_failure_logs_once_and_preserves_error(
    backend_spy, strict, error, level, monkeypatch, caplog, capsys
):
    monkeypatch.setenv("LOG_LEVEL", level)
    backend_spy.read_error = error
    subject = manager(backend_spy)
    if strict:
        with pytest.raises(type(error)) as caught:
            subject.load(strict=True)
        assert caught.value is error
    else:
        assert subject.load() == []
    assert backend_spy.calls == ["read"]
    assert len(caplog.records) == 1
    logged = caplog.records[0]
    assert logged.name == "data_manager"
    assert logged.getMessage() == (
        "Could not read local report history; existing file preserved."
    )
    assert bool(logged.exc_info) is (level == "DEBUG")
    assert logged.levelname == ("ERROR" if level == "DEBUG" else "WARNING")
    assert capsys.readouterr() == ("", "")


def test_manager_read_failure_prevents_write(backend_spy):
    error = OSError("unreadable")
    backend_spy.read_error = error
    with pytest.raises(OSError) as caught:
        manager(backend_spy).save(v2_report())
    assert caught.value is error
    assert backend_spy.calls == ["read"]


def test_manager_write_error_propagates_without_retry(backend_spy):
    error = OSError("unwritable")
    backend_spy.write_error = error
    with pytest.raises(OSError) as caught:
        manager(backend_spy).save(v2_report())
    assert caught.value is error
    assert backend_spy.calls == ["read", "write"]


def test_manager_injected_validator_and_falsey_backend_are_used(backend_spy):
    class ValidatorSpy:
        def __init__(self):
            self.calls = []

        def __bool__(self):
            return False

        def validate_new(self, record):
            self.calls.append(("new", record))
            assert backend_spy.calls == []
            return record

        def validate_stored(self, record):
            self.calls.append(("stored", record))
            assert backend_spy.calls == ["read"]
            return record

    injected = ValidatorSpy()
    backend_spy.records = [{"custom": "history"}]
    record = {"custom": "new"}
    manager(backend_spy, injected).save(record)
    assert injected.calls == [("new", record), ("stored", {"custom": "history"})]
    assert injected.calls[0][1] is record
    assert backend_spy.calls == ["read", "write"]
    assert backend_spy.records == [{"custom": "history"}, {"custom": "new"}]


def test_manager_stored_validation_failure_short_circuits(backend_spy):
    backend_spy.records = [{}, {"score": True}, {"message": "never visited"}]
    with pytest.raises(ValueError):
        manager(backend_spy).save(v2_report())
    assert backend_spy.calls == ["read"]


def test_manager_query_reads_once_and_does_not_write(backend_spy):
    backend_spy.records = [{"message": "first"}, {"message": "second"}]
    assert manager(backend_spy).query(lambda record: True) == backend_spy.records
    assert backend_spy.calls == ["read"]


def test_manager_instances_do_not_share_history(tmp_path):
    first = manager(json_storage(tmp_path / "first.json"))
    second = manager(json_storage(tmp_path / "second.json"))
    first.save(v2_report())
    assert second.load(strict=True) == []
    second.save(v2_report())
    assert first.load(strict=True) == [v2_report()]
    assert second.load(strict=True) == [v2_report()]


def test_manager_defaults_follow_current_directory(tmp_path, monkeypatch):
    subject = manager()
    monkeypatch.chdir(tmp_path)
    subject.save(v2_report())
    assert json_storage(tmp_path / "reports.json").read_records() == [v2_report()]


def test_data_core_exports_storage_and_validator_contracts():
    package = import_module("phishreport.data")
    assert package.ReportValidator is type(validator())
    assert package.ReportStorage is import_module("phishreport.data.storage").ReportStorage
    json_storage = import_module("phishreport.data.json_storage")
    assert package.JsonReportStorage is json_storage.JsonReportStorage


def test_class_shares_mixed_history_and_query(tmp_path):
    path = tmp_path / "custom.json"
    backend = json_storage(path)
    history = [v1_report(), summary_report(), {}, {"unknown": "保留"}]
    backend.write_records(history)
    subject = manager(backend)
    subject.save(v2_report())
    expected = [*history, v2_report()]
    assert subject.load(strict=True) == expected
    assert subject.query(lambda record: record.get("schema_version") == 2) == [v2_report()]


def test_default_storage_uses_current_directory(tmp_path, monkeypatch):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    monkeypatch.chdir(first)
    manager().save(v2_report())
    assert manager().load(strict=True) == [v2_report()]
    monkeypatch.chdir(second)
    assert manager().query(lambda record: True) == []
    assert json_storage(first / "reports.json").read_records() == [v2_report()]
    assert not (second / "reports.json").exists()


@pytest.mark.parametrize("content", [b'{broken', b'[{"score":true}]'])
def test_class_error_handling_preserves_history(tmp_path, content):
    path = tmp_path / "reports.json"
    path.write_bytes(content)
    subject = manager(json_storage(path))
    assert subject.load() == []
    assert subject.query(lambda record: True) == []
    with pytest.raises(ValueError):
        subject.load(strict=True)
    with pytest.raises(ValueError):
        subject.save(v2_report())
    assert path.read_bytes() == content
