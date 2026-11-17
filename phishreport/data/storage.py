"""Storage contract independent of report schema and application policy."""

from abc import ABC, abstractmethod


def replace_revision(records: list[dict], record: dict) -> list[dict]:
    """Return records with the matching assessment revision replaced in place.

    A record without a string assessment_id cannot match stored history, so it
    is appended. When history already contains several copies of the identifier,
    the last one is replaced and the earlier copies are dropped, matching the
    startup repair.
    """
    assessment_id = record.get("assessment_id")
    if not isinstance(assessment_id, str):
        return [*records, record]
    matches = {
        index
        for index, stored in enumerate(records)
        if stored.get("assessment_id") == assessment_id
    }
    if not matches:
        return [*records, record]
    keep = max(matches)
    return [
        record if index == keep else stored
        for index, stored in enumerate(records)
        if index == keep or index not in matches
    ]


def keep_last_revision(records: list[dict]) -> tuple[list[dict], int]:
    """Return records without repeated assessment_ids and the number dropped.

    The last copy of each assessment stays, records without a string
    assessment_id are never treated as duplicates, and surviving records keep
    their relative order.
    """
    last = {}
    for index, record in enumerate(records):
        assessment_id = record.get("assessment_id")
        if isinstance(assessment_id, str):
            last[assessment_id] = index
    kept = []
    removed = 0
    for index, record in enumerate(records):
        assessment_id = record.get("assessment_id")
        if isinstance(assessment_id, str) and last[assessment_id] != index:
            removed += 1
            continue
        kept.append(record)
    return kept, removed


class ReportStorage(ABC):
    """Replace ordered report dictionaries without validating their schema.

    Reads return fresh, independently mutable data, or [] for absent storage.
    Malformed stored contents raise ValueError; I/O errors raise OSError.
    Writes preserve values and order without mutating or retaining mutable
    caller data. Failures before replacement leave prior contents unchanged.
    Implementations propagate failures and do not print or recover silently.
    append adds one record as a single protected operation, so concurrent
    writers cannot discard each other's records. save replaces the record with
    the same assessment_id instead of appending another revision.
    """

    @abstractmethod
    def read_records(self) -> list[dict]:
        """Return an independent snapshot of the complete stored list."""

    @abstractmethod
    def write_records(self, records: list[dict]) -> None:
        """Replace all records, preserving prior contents on pre-replace failure."""

    def append(self, record: dict) -> None:
        """Add one record after the stored ones in a single protected operation.

        This default is read, then write, and is NOT safe against concurrent
        writers. Backends shared between processes override it.
        """
        self.write_records([*self.read_records(), record])

    def save(self, record: dict) -> None:
        """Insert one report revision, replacing the same assessment's copy.

        This default is read, then write, and is NOT safe against concurrent
        writers. Backends shared between processes override it.
        """
        self.write_records(replace_revision(self.read_records(), record))

    def deduplicate_assessments(self) -> int:
        """Drop repeated assessment revisions, keeping the last, and count them.

        This default is read, then write, and is NOT safe against concurrent
        writers. Backends shared between processes override it.
        """
        records, removed = keep_last_revision(self.read_records())
        if removed:
            self.write_records(records)
        return removed
