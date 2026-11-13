"""Strict JSON reads and atomic single-process history replacement."""

import json
import os
import tempfile
from pathlib import Path

from .storage import ReportStorage


class JsonReportStorage(ReportStorage):
    """Store report dictionaries in UTF-8 JSON without validating their schema.

    Relative paths follow the working directory at operation time. Parent
    directories must already exist; atomic writes do not prevent lost updates
    from concurrent writers.
    """

    def __init__(self, path: str | os.PathLike[str] = "reports.json") -> None:
        self._path = Path(path)

    @staticmethod
    def _unique_fields(pairs: list[tuple[str, object]]) -> dict:
        """Reject duplicate fields at every object depth."""
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Local history contains duplicate fields.")
            result[key] = value
        return result

    @staticmethod
    def _invalid_constant(value: str) -> None:
        raise ValueError("Local history contains a non-JSON constant.")

    def read_records(self) -> list[dict]:
        """Decode a complete list of objects; never repair malformed history."""
        try:
            with open(self._path, encoding="utf-8") as stream:
                records = json.load(
                    stream,
                    object_pairs_hook=self._unique_fields,
                    parse_constant=self._invalid_constant,
                )
        except FileNotFoundError:
            return []
        except (ValueError, UnicodeError, RecursionError) as error:
            raise ValueError(
                "Local report history is malformed; existing file preserved."
            ) from error
        if not isinstance(records, list):
            raise ValueError("Local report history must be a list.")
        if any(not isinstance(record, dict) for record in records):
            raise ValueError("Stored reports must be objects.")
        return records

    def write_records(self, records: list[dict]) -> None:
        """Serialize, flush and sync a sibling file before atomic replacement."""
        target = os.path.abspath(self._path)
        temporary = None
        primary_error = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=os.path.dirname(target),
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = stream.name
                json.dump(records, stream, indent=2, ensure_ascii=False, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            temporary = None  # Replacement consumed it; no cleanup is needed.
        except BaseException as error:
            primary_error = error
            raise
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
                except OSError as cleanup_error:
                    if primary_error is None:
                        raise
                    primary_error.add_note(
                        f"Temporary history cleanup failed for {temporary}: {cleanup_error}"
                    )
