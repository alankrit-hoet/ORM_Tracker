"""orm-tracker: find where each ORM activity is pitched in a session transcript.

Give it a transcript file (or paste one on stdin). It prints, per ORM activity,
the timestamp(s) where a trainer pitched it, with the line that triggered the
match so you can eyeball it.

    orm-tracker transcript.vtt
    orm-tracker transcript.vtt --json
    pbpaste | orm-tracker -

No Google, no Sheet, no accounts. The ORM activities and their keywords live in
config.yaml.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config as config_mod
from . import detect, llm, transcript

DEFAULT_CONFIG = "config.yaml"


def _read_input(source: str) -> str:
    if source == "-":
        return sys.stdin.read()
    path = Path(source)
    if not path.is_file():
        raise SystemExit(f"no such transcript file: {source}")
    return path.read_text(encoding="utf-8", errors="replace")


def _print_text(hits: list[detect.Hit], activities) -> None:
    by_activity: dict[str, list[detect.Hit]] = {}
    for hit in hits:
        by_activity.setdefault(hit.activity_id, []).append(hit)

    for activity in activities:
        found = by_activity.get(activity.id, [])
        if not found:
            print(f"\n{activity.name}: not detected")
            continue
        print(f"\n{activity.name}:")
        for hit in found:
            conf = f" ({hit.confidence})" if hit.confidence else ""
            print(f"  {hit.timestamp}{conf}  [{', '.join(hit.matched)}]")
            if hit.quote:
                speaker = f"{hit.speaker}: " if hit.speaker else ""
                print(f"      {speaker}{hit.quote}")


def _print_json(hits: list[detect.Hit], activities) -> None:
    by_activity: dict[str, list[detect.Hit]] = {}
    for hit in hits:
        by_activity.setdefault(hit.activity_id, []).append(hit)

    payload = [
        {
            "id": a.id,
            "activity": a.name,
            "detected": bool(by_activity.get(a.id)),
            "pitches": [
                {
                    "timestamp": h.timestamp,
                    "seconds": int(h.start),
                    "matched": h.matched,
                    "quote": h.quote,
                    "speaker": h.speaker,
                    "confidence": h.confidence,
                }
                for h in by_activity.get(a.id, [])
            ],
        }
        for a in activities
    ]
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orm-tracker", description=__doc__)
    parser.add_argument("transcript", help="transcript file, or '-' to read stdin")
    parser.add_argument("-c", "--config", default=DEFAULT_CONFIG)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    parser.add_argument(
        "--llm",
        action="store_true",
        help="confirm each match with Claude (needs ANTHROPIC_API_KEY)",
    )
    args = parser.parse_args(argv)

    cfg = config_mod.load(args.config)
    detection = cfg.detection
    if args.llm:
        detection = config_mod.dataclasses.replace(detection, llm_confirm=True)

    try:
        cues = transcript.parse(_read_input(args.transcript))
    except transcript.TranscriptError as exc:
        raise SystemExit(
            f"could not read timestamps from this transcript: {exc}\n"
            "A transcript without per-line timestamps cannot give you the "
            "'when'. Export the .vtt/.srt from Zoom or Meet rather than a "
            "plain summary."
        )

    hits = detect.scan(cues, list(cfg.activities), detection)
    if detection.llm_confirm:
        by_id = {a.id: a for a in cfg.activities}
        hits, warnings = llm.confirm(hits, cues, by_id, detection)
        for w in warnings:
            print(f"! {w}", file=sys.stderr)

    if args.json:
        _print_json(hits, cfg.activities)
    else:
        _print_text(hits, cfg.activities)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
