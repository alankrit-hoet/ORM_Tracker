"""Preflight: prove each link in the chain before trusting an empty result.

An ORM tracker fails quietly. Wrong account, folder shared but not the files,
folder names drifted off the convention, transcripts that carry no timestamps
-- every one of those produces "0 pitches found", which is indistinguishable
from a weekend where no trainer pitched anything. This checks each step and
says which one broke.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Config
from .transcript import TranscriptError, parse

OK, WARN, FAIL = "ok", "warn", "fail"
_MARK = {OK: "  ok  ", WARN: " warn ", FAIL: " FAIL "}


@dataclass
class Result:
    status: str
    label: str
    detail: str = ""

    def render(self) -> str:
        line = f"[{_MARK[self.status]}] {self.label}"
        return f"{line}\n         {self.detail}" if self.detail else line


def _folder_results(folders, skipped: list[str]) -> list[Result]:
    out: list[Result] = []
    if folders:
        out.append(
            Result(OK, f"session folders matched: {len(folders)}", f"e.g. {folders[0].name}")
        )
    else:
        out.append(
            Result(
                FAIL,
                "no session folders matched the naming pattern",
                "the folder is reachable but nothing inside it parses as "
                "<date>-<batch>-<title>; check drive.folder_name_pattern",
            )
        )
    if skipped:
        shown = ", ".join(skipped[:3]) + (" ..." if len(skipped) > 3 else "")
        out.append(
            Result(
                WARN,
                f"{len(skipped)} folder(s) skipped, name does not match the pattern",
                shown,
            )
        )
    return out


def _sample_results(drive, cfg: Config, folders, sample: int) -> list[Result]:
    """Actually open a few transcripts. This is where most setups fail."""
    out: list[Result] = []
    checked = missing = unparseable = 0

    for folder in folders[:sample]:
        tfile = drive.find_transcript(folder.id, cfg.drive.transcript_name_hints)
        if tfile is None:
            missing += 1
            out.append(Result(WARN, f"no transcript found in {folder.name}"))
            continue
        try:
            cues = parse(drive.read_text(tfile))
        except TranscriptError as exc:
            unparseable += 1
            out.append(Result(FAIL, f"{folder.name}: {tfile.name}", str(exc)))
            continue
        except Exception as exc:  # noqa: BLE001 - surface the API error verbatim
            out.append(Result(FAIL, f"{folder.name}: could not read {tfile.name}", str(exc)))
            continue
        checked += 1
        out.append(
            Result(
                OK,
                f"{folder.name}: {tfile.name}",
                f"{len(cues)} timestamped cues, last at {int(cues[-1].start) // 60} min",
            )
        )

    if checked == 0 and (missing or unparseable):
        out.append(
            Result(
                FAIL,
                "no sampled session yielded a usable transcript",
                "the tracker would report every activity as Not Detected",
            )
        )
    return out


def run(drive, cfg: Config, sheet_writer=None, sample: int = 3) -> list[Result]:
    results: list[Result] = []

    try:
        folders, skipped = drive.session_folders(cfg.drive)
    except Exception as exc:  # noqa: BLE001
        return [
            Result(
                FAIL,
                f"cannot list folder {cfg.drive.root_folder_id}",
                f"{exc}\n         The credentials authenticated, but this "
                f"account cannot see that folder. For a Shared Drive the "
                f"service account must be a MEMBER of the drive -- sharing "
                f"the folder alone is often not enough.",
            )
        ]

    results.append(Result(OK, f"reached Drive folder {cfg.drive.root_folder_id}"))
    results.extend(_folder_results(folders, skipped))
    if folders:
        results.extend(_sample_results(drive, cfg, folders, sample))

    results.append(
        Result(OK, f"{len(cfg.activities)} ORM activit(ies) configured",
               ", ".join(a.name for a in cfg.activities))
    )

    if sheet_writer is None:
        results.append(
            Result(WARN, "no sheet.spreadsheet_id set", "results would go to CSV")
        )
    else:
        try:
            sheet_writer.probe()
            results.append(Result(OK, "target Sheet is writable"))
        except Exception as exc:  # noqa: BLE001
            results.append(
                Result(
                    FAIL,
                    "cannot write to the target Sheet",
                    f"{exc}\n         Share the Sheet with the service account "
                    f"as an Editor.",
                )
            )

    return results


def report(results: list[Result]) -> int:
    for r in results:
        print(r.render())
    failed = sum(1 for r in results if r.status == FAIL)
    warned = sum(1 for r in results if r.status == WARN)
    print(f"\n{failed} failure(s), {warned} warning(s)")
    return 1 if failed else 0
