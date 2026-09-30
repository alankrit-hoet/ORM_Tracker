"""Load and validate config.yaml: the ORM activities and how strict to be."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Activity:
    id: str
    name: str
    description: str = ""
    strong_keywords: tuple[str, ...] = ()
    support_keywords: tuple[str, ...] = ()
    exclude_keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class DetectionConfig:
    window_seconds: int = 90
    min_score: float = 2.0
    strong_weight: float = 2.0
    support_weight: float = 0.5
    merge_gap_seconds: int = 180
    report: str = "all"
    llm_confirm: bool = False
    llm_model: str = "claude-sonnet-5-5"


@dataclass(frozen=True)
class Config:
    detection: DetectionConfig
    activities: tuple[Activity, ...] = ()


def _activity(raw: dict[str, Any]) -> Activity:
    missing = [k for k in ("id", "name") if not raw.get(k)]
    if missing:
        raise ValueError(f"activity is missing required key(s) {missing}: {raw!r}")
    if not raw.get("strong_keywords"):
        raise ValueError(
            f"activity {raw['id']!r} has no strong_keywords; it would never match"
        )
    return Activity(
        id=str(raw["id"]),
        name=str(raw["name"]),
        description=str(raw.get("description", "") or "").strip(),
        strong_keywords=tuple(str(k) for k in raw.get("strong_keywords", [])),
        support_keywords=tuple(str(k) for k in raw.get("support_keywords", [])),
        exclude_keywords=tuple(str(k) for k in raw.get("exclude_keywords", [])),
    )


def load(path: str | Path) -> Config:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}

    det_raw = raw.get("detection") or {}
    detection = DetectionConfig(
        window_seconds=int(det_raw.get("window_seconds", 90)),
        min_score=float(det_raw.get("min_score", 2.0)),
        strong_weight=float(det_raw.get("strong_weight", 2.0)),
        support_weight=float(det_raw.get("support_weight", 0.5)),
        merge_gap_seconds=int(det_raw.get("merge_gap_seconds", 180)),
        report=str(det_raw.get("report", "all")),
        llm_confirm=bool(det_raw.get("llm_confirm", False)),
        llm_model=str(det_raw.get("llm_model", "claude-sonnet-5-5")),
    )
    if detection.report not in ("all", "first"):
        raise ValueError("detection.report must be 'all' or 'first'")

    activities = tuple(_activity(a) for a in (raw.get("activities") or []))
    if not activities:
        raise ValueError("no activities configured; nothing to look for")

    seen: set[str] = set()
    for a in activities:
        if a.id in seen:
            raise ValueError(f"duplicate activity id {a.id!r}")
        seen.add(a.id)

    return Config(detection=detection, activities=activities)
