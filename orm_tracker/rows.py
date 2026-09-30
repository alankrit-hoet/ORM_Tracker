"""The tracker's output row shape, shared by the CSV and Sheet writers."""

from __future__ import annotations

from dataclasses import asdict, dataclass

HEADERS = [
    "Key",
    "Date",
    "Batch",
    "Session Title",
    "ORM Activity",
    "Detected",
    "Timestamp",
    "Timestamp (sec)",
    "Quote",
    "Speaker",
    "Matched Keywords",
    "Confidence",
    "Method",
    "Session Folder",
    "Transcript File",
    "Last Updated",
]


@dataclass
class Row:
    key: str
    date: str
    batch: str
    session_title: str
    activity: str
    detected: str
    timestamp: str
    timestamp_sec: str
    quote: str
    speaker: str
    matched: str
    confidence: str
    method: str
    folder_url: str
    transcript_url: str
    updated: str

    def as_list(self) -> list[str]:
        return [str(v) for v in asdict(self).values()]
