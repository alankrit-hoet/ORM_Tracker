"""Find where an ORM activity is pitched inside a parsed transcript.

Two stages, the second optional:

1. Keyword scan over rolling time windows. Cheap, deterministic, and good at
   recall. It is deliberately not the final word -- "review" and "post" show up
   constantly in a training session for reasons that have nothing to do with ORM.
2. An LLM confirmation pass over the candidates from stage 1 (see llm.py).
   This is what turns recall into precision. Enable it in config.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .config import Activity, DetectionConfig
from .transcript import Cue, format_timestamp


@dataclass
class Hit:
    activity_id: str
    activity_name: str
    start: float
    end: float
    score: float
    matched: list[str] = field(default_factory=list)
    quote: str = ""
    speaker: str = ""
    method: str = "keyword"
    confidence: str = ""

    @property
    def timestamp(self) -> str:
        return format_timestamp(self.start)


def _pattern(keyword: str) -> re.Pattern[str]:
    """Whole-word, case-insensitive, whitespace-tolerant phrase match."""
    parts = [re.escape(p) for p in keyword.lower().split()]
    return re.compile(r"\b" + r"\s+".join(parts) + r"\b", re.IGNORECASE)


class _CompiledActivity:
    __slots__ = ("activity", "strong", "support", "exclude")

    def __init__(self, activity: Activity):
        self.activity = activity
        self.strong = [(k, _pattern(k)) for k in activity.strong_keywords]
        self.support = [(k, _pattern(k)) for k in activity.support_keywords]
        self.exclude = [_pattern(k) for k in activity.exclude_keywords]


def _windows(cues: list[Cue], seconds: int) -> list[tuple[float, float, list[Cue]]]:
    """Rolling windows anchored on each cue, covering `seconds` of speech.

    Anchoring on cues (rather than a fixed grid) means a pitch is never split
    across a boundary in a way that halves its keyword score.
    """
    out: list[tuple[float, float, list[Cue]]] = []
    for i, cue in enumerate(cues):
        limit = cue.start + seconds
        group = [cue]
        for nxt in cues[i + 1:]:
            if nxt.start > limit:
                break
            group.append(nxt)
        out.append((cue.start, group[-1].end, group))
    return out


def _merge(hits: list[Hit], gap: int) -> list[Hit]:
    """Collapse overlapping/adjacent windows into one pitch, keeping the best."""
    if not hits:
        return []
    hits = sorted(hits, key=lambda h: h.start)
    merged = [hits[0]]
    for h in hits[1:]:
        last = merged[-1]
        if h.start - last.end <= gap:
            if h.score > last.score:
                # Keep the earliest start -- that is when the pitch began.
                h.start = last.start
                h.matched = sorted(set(last.matched) | set(h.matched))
                merged[-1] = h
            else:
                last.end = max(last.end, h.end)
                last.matched = sorted(set(last.matched) | set(h.matched))
        else:
            merged.append(h)
    return merged


def scan(
    cues: list[Cue],
    activities: list[Activity],
    cfg: DetectionConfig,
) -> list[Hit]:
    """Return keyword candidates for every activity, merged and ordered."""
    compiled = [_CompiledActivity(a) for a in activities]
    windows = _windows(cues, cfg.window_seconds)
    results: list[Hit] = []

    for ca in compiled:
        raw: list[Hit] = []
        for _, end, group in windows:
            text = " ".join(c.text for c in group)
            if any(p.search(text) for p in ca.exclude):
                continue

            strong = {k for k, p in ca.strong if p.search(text)}
            if not strong:
                continue
            support = {k for k, p in ca.support if p.search(text)}

            score = len(strong) * cfg.strong_weight + len(support) * cfg.support_weight
            if score < cfg.min_score:
                continue

            anchor = next(
                (c for c in group if any(p.search(c.text) for _, p in ca.strong)),
                group[0],
            )
            raw.append(
                Hit(
                    activity_id=ca.activity.id,
                    activity_name=ca.activity.name,
                    # The pitch starts where the activity is actually named,
                    # not where the scoring window happens to open.
                    start=anchor.start,
                    end=max(end, anchor.end),
                    score=score,
                    matched=sorted(strong | support),
                    quote=anchor.text.strip()[:400],
                    speaker=anchor.speaker,
                )
            )

        merged = _merge(raw, cfg.merge_gap_seconds)
        if cfg.report == "first":
            merged = merged[:1]
        results.extend(merged)

    return sorted(results, key=lambda h: (h.start, h.activity_id))


def window_text(cues: list[Cue], start: float, end: float, pad: float = 30.0) -> str:
    """Transcript text around a hit, for the LLM confirmation prompt."""
    lines = [
        f"[{format_timestamp(c.start)}] {c.speaker + ': ' if c.speaker else ''}{c.text}"
        for c in cues
        if c.end >= start - pad and c.start <= end + pad
    ]
    return "\n".join(lines)
