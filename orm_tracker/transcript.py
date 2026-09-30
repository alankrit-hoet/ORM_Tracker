"""Parse transcripts into timestamped cues.

Supports WebVTT and SRT (what Zoom and Google Meet write to Drive), Zoom's
plain-text transcript export, and a loose fallback for text that merely has
HH:MM:SS stamps at the start of lines (e.g. a transcript pasted into a Doc).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 00:01:02.345 / 00:01:02,345 / 01:02.345 / 1:02:03
_TS = r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:[.,](\d{1,3}))?"
_CUE_RANGE = re.compile(rf"^\s*{_TS}\s*-->\s*{_TS}")
_LEADING_TS = re.compile(rf"^\s*\[?{_TS}\]?\s*[-–:]?\s*")
_SPEAKER = re.compile(r"^\s*([^:>]{1,60}?)\s*:\s+(.*)$")
_TAG = re.compile(r"</?[^>]+>")


class TranscriptError(ValueError):
    """The file could not be parsed into timestamped cues."""


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    speaker: str
    text: str


def _seconds(h: str | None, m: str, s: str, ms: str | None) -> float:
    total = int(m) * 60 + int(s)
    if h:
        total += int(h) * 3600
    if ms:
        total += int(ms.ljust(3, "0")) / 1000.0
    return float(total)


def _split_speaker(line: str) -> tuple[str, str]:
    m = _SPEAKER.match(line)
    if not m:
        return "", line.strip()
    speaker, rest = m.group(1).strip(), m.group(2).strip()
    # "so here is the thing: ..." is a sentence, not a speaker label. Real
    # labels are short -- "Nisha", "Ashutosh Goel", "Amit (Be10x)".
    if len(speaker.split()) > 3 or speaker.endswith((",", ".", "!", "?")):
        return "", line.strip()
    return speaker, rest


def format_timestamp(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def _parse_cue_blocks(text: str) -> list[Cue]:
    """WebVTT / SRT: a timing line followed by one or more text lines."""
    cues: list[Cue] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = _CUE_RANGE.match(lines[i])
        if not m:
            i += 1
            continue
        start = _seconds(*m.group(1, 2, 3, 4))
        end = _seconds(*m.group(5, 6, 7, 8))
        i += 1
        body: list[str] = []
        while i < len(lines) and lines[i].strip() and not _CUE_RANGE.match(lines[i]):
            body.append(_TAG.sub("", lines[i]).strip())
            i += 1
        if not body:
            continue
        speaker, first = _split_speaker(body[0])
        payload = " ".join([first, *body[1:]]).strip()
        if payload:
            cues.append(Cue(start, max(end, start), speaker, payload))
    return cues


def _parse_leading_timestamps(text: str) -> list[Cue]:
    """Fallback: lines that begin with a timestamp."""
    cues: list[Cue] = []
    for line in text.splitlines():
        m = _LEADING_TS.match(line)
        if not m:
            continue
        rest = line[m.end():].strip()
        if not rest:
            continue
        speaker, payload = _split_speaker(rest)
        if payload:
            cues.append(Cue(_seconds(*m.group(1, 2, 3, 4)), 0.0, speaker, payload))
    # Give each cue an end time from the next cue's start.
    out: list[Cue] = []
    for idx, c in enumerate(cues):
        end = cues[idx + 1].start if idx + 1 < len(cues) else c.start + 5.0
        out.append(Cue(c.start, max(end, c.start), c.speaker, c.text))
    return out


def parse(text: str) -> list[Cue]:
    """Parse transcript text into cues ordered by start time.

    Raises TranscriptError if no timestamps could be found -- a transcript
    without timestamps cannot answer "when was this pitched", and silently
    returning nothing would look identical to "the activity never happened".
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    cues = _parse_cue_blocks(text) or _parse_leading_timestamps(text)
    if not cues:
        raise TranscriptError(
            "no timestamps found; transcript format is unsupported or the file "
            "carries no timing information"
        )
    return sorted(cues, key=lambda c: c.start)
