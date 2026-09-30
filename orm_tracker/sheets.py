"""Write the tracker into a Google Sheet, upserting by a stable row key.

Rerunning the tracker must not duplicate rows, and must pick up corrections
(a transcript re-uploaded, an activity's keywords tightened). So every row
carries a key of "<session folder id>|<activity id>|<timestamp>" and existing
rows with that key are overwritten in place.
"""

from __future__ import annotations

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .rows import HEADERS, Row

SCOPES_RW = ["https://www.googleapis.com/auth/spreadsheets"]

__all__ = ["SCOPES_RW", "HEADERS", "Row", "SheetWriter"]

def _a1(worksheet: str, ref: str) -> str:
    return f"'{worksheet.replace(chr(39), chr(39) * 2)}'!{ref}"


class SheetWriter:
    def __init__(self, credentials, spreadsheet_id: str, worksheet: str):
        self._svc = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        self._id = spreadsheet_id
        self._ws = worksheet

    def _ensure_worksheet(self) -> None:
        meta = self._svc.spreadsheets().get(spreadsheetId=self._id).execute()
        names = {s["properties"]["title"] for s in meta.get("sheets", [])}
        if self._ws in names:
            return
        self._svc.spreadsheets().batchUpdate(
            spreadsheetId=self._id,
            body={"requests": [{"addSheet": {"properties": {"title": self._ws}}}]},
        ).execute()

    def _read(self) -> list[list[str]]:
        try:
            resp = (
                self._svc.spreadsheets()
                .values()
                .get(spreadsheetId=self._id, range=_a1(self._ws, "A:P"))
                .execute()
            )
        except HttpError:
            return []
        return resp.get("values", [])

    def upsert(self, rows: list[Row]) -> tuple[int, int]:
        """Write rows. Returns (updated, appended)."""
        self._ensure_worksheet()
        existing = self._read()

        if not existing or [c.strip() for c in existing[0][: len(HEADERS)]] != HEADERS:
            self._svc.spreadsheets().values().update(
                spreadsheetId=self._id,
                range=_a1(self._ws, "A1"),
                valueInputOption="RAW",
                body={"values": [HEADERS]},
            ).execute()
            existing = [HEADERS]

        # Row number in the sheet (1-indexed, header is row 1).
        index = {
            row[0]: n
            for n, row in enumerate(existing[1:], start=2)
            if row and row[0]
        }

        updates: list[dict] = []
        appends: list[list[str]] = []
        for row in rows:
            values = row.as_list()
            line = index.get(row.key)
            if line:
                updates.append(
                    {"range": _a1(self._ws, f"A{line}"), "values": [values]}
                )
            else:
                appends.append(values)

        if updates:
            self._svc.spreadsheets().values().batchUpdate(
                spreadsheetId=self._id,
                body={"valueInputOption": "RAW", "data": updates},
            ).execute()

        if appends:
            self._svc.spreadsheets().values().append(
                spreadsheetId=self._id,
                range=_a1(self._ws, "A1"),
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": appends},
            ).execute()

        return len(updates), len(appends)
