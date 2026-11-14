"""Immutable JSON ownership for the report model foundation."""

import math
from collections import UserDict
from types import MappingProxyType

import pytest

from phishreport.model import SCHEMA_VERSION, SCHEMA_VERSION_KEY, _freeze_json


def test_report_model_owns_schema_version_constants():
    assert SCHEMA_VERSION == 3
    assert SCHEMA_VERSION_KEY == "schema_version"


def test_freeze_json_owns_nested_input_and_unknown_legacy_fields():
    original = {
        "result": {"reasons": ["Original reason"], "trace": [{"matched": True}]},
        "unknown_legacy_extra": {"labels": ["original", {"details": [1, 2]}]},
    }

    frozen = _freeze_json(original)
    original["result"]["reasons"].append("Later reason")
    original["result"]["trace"][0]["matched"] = False
    original["unknown_legacy_extra"]["labels"][0] = "changed"
    original["unknown_legacy_extra"]["labels"][1]["details"].append(3)
    original["new_field"] = "not owned"

    assert isinstance(frozen, MappingProxyType)
    assert frozen["result"]["reasons"] == ("Original reason",)
    assert frozen["result"]["trace"][0]["matched"] is True
    assert frozen["unknown_legacy_extra"]["labels"][0] == "original"
    assert frozen["unknown_legacy_extra"]["labels"][1]["details"] == (1, 2)
    assert "new_field" not in frozen


def test_freeze_json_rejects_mutations_at_every_container_level():
    frozen = _freeze_json({"items": [{"values": [1]}]})

    with pytest.raises(TypeError):
        frozen["items"] = ()
    with pytest.raises(TypeError):
        frozen["items"][0] = {}
    with pytest.raises(TypeError):
        frozen["items"][0]["values"] = ()
    with pytest.raises(AttributeError):
        frozen["items"][0]["values"].append(2)


def test_freeze_json_does_not_retain_mutable_aliases_between_original_branches():
    shared_list = ["kept"]
    shared_mapping = {"items": shared_list}
    original = {"left": shared_mapping, "right": shared_mapping, "items": shared_list}

    frozen = _freeze_json(original)
    shared_mapping["extra"] = "new"
    shared_list.clear()

    assert frozen["left"]["items"] == frozen["right"]["items"] == frozen["items"] == ("kept",)
    assert frozen["left"] is not shared_mapping and frozen["right"] is not shared_mapping
    assert frozen["left"]["items"] is not shared_list
    assert "extra" not in frozen["left"] and "extra" not in frozen["right"]


def test_freeze_json_accepts_mapping_protocol_and_tuples_without_mutable_aliases():
    original = UserDict({"items": (["before"],)})

    frozen = _freeze_json(original)
    original["items"][0].append("after")

    assert isinstance(frozen, MappingProxyType)
    assert frozen["items"] == (("before",),)


@pytest.mark.parametrize("value", [None, "", "Text", True, False, 0, -3, 2**80, 0.0, -1.25])
def test_freeze_json_preserves_scalar_values_without_coercion(value):
    assert _freeze_json(value) is value


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_freeze_json_does_not_normalize_nonfinite_legacy_float_values(value):
    frozen = _freeze_json(value)

    assert frozen is value
    assert math.isnan(frozen) if math.isnan(value) else frozen == value


@pytest.mark.parametrize("value", [object(), {"private-value"}, bytearray(b"private"), b"private"])
def test_freeze_json_rejects_unsupported_types_with_fixed_safe_message(value):
    original = {"items": ["preserved", value]}

    with pytest.raises(ValueError) as caught:
        _freeze_json(original)

    assert "private" not in str(caught.value)
    assert str(caught.value) == (
        "Report data must use JSON-compatible values and string object keys."
    )
    assert original["items"][0] == "preserved" and original["items"][1] is value


@pytest.mark.parametrize("key", [1, True, None, ("private",)])
def test_freeze_json_rejects_non_string_mapping_keys_without_changing_input(key):
    nested = ["preserved"]
    original = {"valid": nested, key: "private-value"}

    with pytest.raises(ValueError) as caught:
        _freeze_json(original)

    assert str(caught.value) == (
        "Report data must use JSON-compatible values and string object keys."
    )
    assert original["valid"] is nested and nested == ["preserved"]
    assert original[key] == "private-value"


def test_freeze_json_error_does_not_format_unsupported_objects():
    class Unprintable:
        def __repr__(self):
            raise AssertionError("Unsupported data must not be formatted")

    with pytest.raises(ValueError, match="JSON-compatible"):
        _freeze_json({"unknown": Unprintable()})
