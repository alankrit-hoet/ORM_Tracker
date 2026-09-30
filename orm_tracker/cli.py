"""orm-tracker: scan session transcripts in Drive, record ORM pitches in a Sheet."""

from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import config as config_mod
from . import detect, llm, transcript
from .rows import HEADERS, Row

DEFAULT_CONFIG = "config.yaml"
DEFAULT_STATE = "state.json"
DEFAULT_CSV = "out/orm_tracker.csv"


def _credentials(scopes: list[str]):
    """Service-account credentials from GOOGLE_APPLICATION_CREDENTIALS.

    A service account is the right fit here: no browser consent, no refresh
    token to babysit, and it can be added to the Shared Drive as a member.
    """
    from google.oauth2 import service_account

    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if not path:
        raise SystemExit(
            "GOOGLE_APPLICATION_CREDENTIALS is not set. Point it at the service "
            "account JSON key, and give that account Viewer on the Drive folder "
            "and Editor on the Sheet."
        )
    if not Path(path).is_file():
        raise SystemExit(f"GOOGLE_APPLICATION_CREDENTIALS points at a missing file: {path}")
    return service_account.Credentials.from_service_account_file(path, scopes=scopes)


def _load_state(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, rows: list[Row]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADERS)
        for row in rows:
            writer.writerow(row.as_list())


def _rows_for_session(folder, tfile, hits, activities, now: str) -> list[Row]:
    """One row per detected pitch; one 'Not found' row per activity with none."""
    rows: list[Row] = []
    found: set[str] = set()

    for hit in hits:
        found.add(hit.activity_id)
        rows.append(
            Row(
                key=f"{folder.id}|{hit.activity_id}|{hit.timestamp}",
                date=folder.date,
                batch=folder.batch,
                session_title=folder.title,
                activity=hit.activity_name,
                detected="Yes",
                timestamp=hit.timestamp,
                timestamp_sec=str(int(hit.start)),
                quote=hit.quote,
                speaker=hit.speaker,
                matched=", ".join(hit.matched),
                confidence=hit.confidence,
                method=hit.method,
                folder_url=folder.url,
                transcript_url=tfile.url if tfile else "",
                updated=now,
            )
        )

    for activity in activities:
        if activity.id in found:
            continue
        rows.append(
            Row(
                key=f"{folder.id}|{activity.id}|-",
                date=folder.date,
                batch=folder.batch,
                session_title=folder.title,
                activity=activity.name,
                detected="No",
                timestamp="",
                timestamp_sec="",
                quote="",
                speaker="",
                matched="",
                confidence="",
                method="",
                folder_url=folder.url,
                transcript_url=tfile.url if tfile else "",
                updated=now,
            )
        )
    return rows


class _LocalFolder:
    """Stands in for a Drive session folder when running against local files."""

    def __init__(self, path: Path, date: str, batch: str, title: str):
        self.id = f"local:{path.name}"
        self.name = path.stem
        self.date, self.batch, self.title = date, batch, title
        self.url = str(path.resolve())


class _LocalFile:
    def __init__(self, path: Path):
        self.url = str(path.resolve())


def run_local(cfg, args: argparse.Namespace) -> int:
    """Scan transcript files in a directory. No Drive, no Sheet, no credentials.

    Each file is one session; its name (minus extension) is parsed with the
    same <date>-<batch>-<title> pattern. Use this to tune keywords before
    pointing the tracker at Drive.
    """
    directory = Path(args.local_dir)
    if not directory.is_dir():
        raise SystemExit(f"--local-dir is not a directory: {directory}")

    regex = cfg.drive.folder_regex
    by_id = {a.id: a for a in cfg.activities}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    rows: list[Row] = []

    files = sorted(p for p in directory.iterdir() if p.is_file())
    if not files:
        raise SystemExit(f"no files in {directory}")

    for path in files:
        m = regex.match(path.stem)
        groups = m.groupdict() if m else {}
        folder = _LocalFolder(
            path,
            (groups.get("date") or "").strip(),
            (groups.get("batch") or "").strip(),
            (groups.get("title") or path.stem).strip(),
        )
        try:
            cues = transcript.parse(path.read_text(encoding="utf-8", errors="replace"))
        except transcript.TranscriptError as exc:
            print(f"  ! {path.name}: {exc}", file=sys.stderr)
            continue

        hits = detect.scan(cues, list(cfg.activities), cfg.detection)
        if cfg.detection.llm_confirm:
            hits, warnings = llm.confirm(hits, cues, by_id, cfg.detection)
            for w in warnings:
                print(f"  ! {path.name}: {w}", file=sys.stderr)

        for hit in hits:
            print(f"  {path.name}  {hit.timestamp}  {hit.activity_name}  [{', '.join(hit.matched)}]")
            print(f"      {hit.quote[:160]}")
        if not hits:
            print(f"  {path.name}: no ORM activity detected ({len(cues)} cues)")

        rows.extend(_rows_for_session(folder, _LocalFile(path), hits, cfg.activities, now))

    _write_csv(Path(args.csv), rows)
    print(f"csv: {len(rows)} row(s) -> {args.csv}")
    return 0


def run(args: argparse.Namespace) -> int:
    cfg = config_mod.load(args.config)
    if args.local_dir:
        return run_local(cfg, args)
    state_path = Path(args.state)
    state = {} if args.full else _load_state(state_path)

    # Imported here, not at module load, so --local-dir needs no Google SDK.
    from .drive import SCOPES_RO, DriveClient, folder_id_from
    from .sheets import SCOPES_RW, SheetWriter

    scopes = list(SCOPES_RO)
    if cfg.sheet.spreadsheet_id and not args.csv_only:
        scopes += SCOPES_RW
    if args.folder:
        cfg = dataclasses.replace(
            cfg,
            drive=dataclasses.replace(
                cfg.drive, root_folder_id=folder_id_from(args.folder)
            ),
        )

    drive = DriveClient(_credentials(scopes))

    folders, skipped = drive.session_folders(cfg.drive)
    print(f"session folders matched: {len(folders)}")
    for name in skipped:
        print(f"  skipped (name does not match pattern): {name}", file=sys.stderr)
    if not folders:
        print("nothing to do", file=sys.stderr)
        return 1

    by_id = {a.id: a for a in cfg.activities}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    rows: list[Row] = []
    processed = 0

    for folder in folders:
        tfile = drive.find_transcript(folder.id, cfg.drive.transcript_name_hints)
        if tfile is None:
            print(f"  ! no transcript in {folder.name}", file=sys.stderr)
            continue

        fingerprint = f"{tfile.id}:{tfile.modified_time}"
        if state.get(folder.id) == fingerprint:
            continue

        try:
            cues = transcript.parse(drive.read_text(tfile))
        except transcript.TranscriptError as exc:
            print(f"  ! {folder.name}: {exc}", file=sys.stderr)
            continue

        hits = detect.scan(cues, list(cfg.activities), cfg.detection)
        if cfg.detection.llm_confirm:
            hits, warnings = llm.confirm(hits, cues, by_id, cfg.detection)
            for w in warnings:
                print(f"  ! {folder.name}: {w}", file=sys.stderr)

        rows.extend(_rows_for_session(folder, tfile, hits, cfg.activities, now))
        state[folder.id] = fingerprint
        processed += 1
        print(f"  {folder.name}: {len(hits)} pitch(es) across {len(cues)} cues")

    if not rows:
        print("no new or changed sessions")
        return 0

    if cfg.sheet.spreadsheet_id and not args.csv_only:
        writer = SheetWriter(
            _credentials(scopes), cfg.sheet.spreadsheet_id, cfg.sheet.worksheet
        )
        updated, appended = writer.upsert(rows)
        print(f"sheet: {appended} row(s) added, {updated} updated")
    else:
        _write_csv(Path(args.csv), rows)
        print(f"csv: {len(rows)} row(s) -> {args.csv}")

    if not args.no_state:
        _save_state(state_path, state)
    print(f"sessions processed: {processed}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orm-tracker", description=__doc__)
    parser.add_argument("-c", "--config", default=DEFAULT_CONFIG)
    parser.add_argument("--folder", help="override drive.root_folder_id (id or URL)")
    parser.add_argument(
        "--local-dir",
        help="scan transcript files in this directory instead of Drive (no credentials needed)",
    )
    parser.add_argument("--state", default=DEFAULT_STATE)
    parser.add_argument("--full", action="store_true", help="reprocess every session")
    parser.add_argument("--no-state", action="store_true", help="do not persist state")
    parser.add_argument("--csv-only", action="store_true", help="skip the Sheet")
    parser.add_argument("--csv", default=DEFAULT_CSV)
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
