"""Google Drive access: enumerate session folders and fetch their transcripts."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from .config import DriveConfig

SCOPES_RO = ["https://www.googleapis.com/auth/drive.readonly"]

_FOLDER = "application/vnd.google-apps.folder"
_SHORTCUT = "application/vnd.google-apps.shortcut"
_GDOC = "application/vnd.google-apps.document"
_FIELDS = (
    "nextPageToken, files(id, name, mimeType, modifiedTime, "
    "shortcutDetails(targetId, targetMimeType))"
)
# Shared-drive support has to be opted into on every single call.
_SHARED = {"supportsAllDrives": True, "includeItemsFromAllDrives": True}


@dataclass(frozen=True)
class SessionFolder:
    id: str
    name: str
    date: str
    batch: str
    title: str

    @property
    def url(self) -> str:
        return f"https://drive.google.com/drive/folders/{self.id}"


@dataclass(frozen=True)
class TranscriptFile:
    id: str
    name: str
    mime_type: str
    modified_time: str

    @property
    def url(self) -> str:
        return f"https://drive.google.com/file/d/{self.id}/view"


class DriveClient:
    def __init__(self, credentials):
        self._svc = build("drive", "v3", credentials=credentials, cache_discovery=False)

    def _list(self, query: str) -> list[dict]:
        files: list[dict] = []
        token = None
        while True:
            resp = (
                self._svc.files()
                .list(
                    q=query,
                    fields=_FIELDS,
                    pageSize=200,
                    pageToken=token,
                    **_SHARED,
                )
                .execute()
            )
            files.extend(resp.get("files", []))
            token = resp.get("nextPageToken")
            if not token:
                return files

    def _resolve(self, item: dict) -> dict:
        """Follow a Drive shortcut to the file it points at."""
        if item.get("mimeType") != _SHORTCUT:
            return item
        target = (item.get("shortcutDetails") or {}).get("targetId")
        if not target:
            return item
        try:
            resolved = (
                self._svc.files()
                .get(
                    fileId=target,
                    fields="id, name, mimeType, modifiedTime",
                    supportsAllDrives=True,
                )
                .execute()
            )
        except HttpError:
            return item
        resolved.setdefault("name", item.get("name", ""))
        return resolved

    def session_folders(self, cfg: DriveConfig) -> tuple[list[SessionFolder], list[str]]:
        """Sub-folders of the root, parsed as <date>-<batch>-<title>.

        Folders that do not match the pattern are reported rather than dropped
        silently -- a rename convention drifting is exactly the kind of thing
        that quietly empties a tracker.
        """
        query = f"'{cfg.root_folder_id}' in parents and mimeType = '{_FOLDER}' and trashed = false"
        regex = cfg.folder_regex
        folders: list[SessionFolder] = []
        skipped: list[str] = []
        for item in self._list(query):
            name = item.get("name", "")
            m = regex.match(name)
            if not m:
                skipped.append(name)
                continue
            groups = m.groupdict()
            folders.append(
                SessionFolder(
                    id=item["id"],
                    name=name,
                    date=(groups.get("date") or "").strip(),
                    batch=(groups.get("batch") or "").strip(),
                    title=(groups.get("title") or "").strip(),
                )
            )
        folders.sort(key=lambda f: f.name)
        return folders, skipped

    def find_transcript(self, folder_id: str, hints: tuple[str, ...]) -> TranscriptFile | None:
        """Best transcript in a folder, preferring earlier hints."""
        items = [
            self._resolve(i)
            for i in self._list(f"'{folder_id}' in parents and trashed = false")
        ]
        candidates = [i for i in items if i.get("mimeType") != _FOLDER]
        for hint in hints:
            for item in candidates:
                if hint in item.get("name", "").lower():
                    return TranscriptFile(
                        id=item["id"],
                        name=item.get("name", ""),
                        mime_type=item.get("mimeType", ""),
                        modified_time=item.get("modifiedTime", ""),
                    )
        return None

    def read_text(self, file: TranscriptFile) -> str:
        if file.mime_type == _GDOC:
            data = (
                self._svc.files()
                .export(fileId=file.id, mimeType="text/plain")
                .execute()
            )
        else:
            request = self._svc.files().get_media(fileId=file.id, supportsAllDrives=True)
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            data = buffer.getvalue()
        if isinstance(data, str):
            return data
        return data.decode("utf-8", errors="replace")


def folder_id_from(value: str) -> str:
    """Accept either a raw folder id or a Drive URL."""
    m = re.search(r"/folders/([A-Za-z0-9_-]+)", value)
    return m.group(1) if m else value.strip()
