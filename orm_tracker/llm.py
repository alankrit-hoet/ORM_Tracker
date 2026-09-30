"""Optional confirmation pass: ask Claude whether a candidate is a real pitch.

Keyword matching over-fires. A trainer saying "let's review what we covered"
trips a review keyword; "post this in the group" trips a LinkedIn one. This
pass reads the surrounding transcript and decides. It also refines the start
timestamp to where the pitch actually begins.

Requires ANTHROPIC_API_KEY. If the key is absent or the call fails, candidates
are returned unchanged and flagged as keyword-only, so a broken API key
degrades the tracker's precision rather than losing a session's data.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

from .config import Activity, DetectionConfig
from .detect import Hit, window_text
from .transcript import Cue

_API = "https://api.anthropic.com/v1/messages"
_TS_RE = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2})$")

_PROMPT = """You are auditing a live training-session transcript.

ORM activity: {name}
What counts as a pitch: {description}

Below is an excerpt. Decide whether the trainer actually PITCHES this activity
to the learners here -- asking them to do it, telling them it is coming, or
walking them through it. An incidental mention of the same words, a learner
asking an unrelated question, or the trainer using the words in another sense
is NOT a pitch.

Reply with JSON only:
{{"is_pitch": true|false, "start": "HH:MM:SS", "confidence": "high"|"medium"|"low", "quote": "<the sentence that starts the pitch>"}}

"start" must be a timestamp that appears in the excerpt, marking where the
pitch begins. If is_pitch is false, use the excerpt's first timestamp.

Excerpt:
{excerpt}
"""


class LLMUnavailable(RuntimeError):
    pass


def _call(model: str, prompt: str, api_key: str, timeout: int = 60) -> str:
    body = json.dumps(
        {
            "model": model,
            "max_tokens": 400,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        _API,
        data=body,
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise LLMUnavailable(str(exc)) from exc
    return "".join(
        block.get("text", "") for block in payload.get("content", []) if isinstance(block, dict)
    )


def _parse_verdict(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _to_seconds(value: str) -> float | None:
    m = _TS_RE.match(value.strip())
    if not m:
        return None
    h, mi, s = (int(g) for g in m.groups())
    return float(h * 3600 + mi * 60 + s)


def confirm(
    hits: list[Hit],
    cues: list[Cue],
    activities: dict[str, Activity],
    cfg: DetectionConfig,
) -> tuple[list[Hit], list[str]]:
    """Filter hits down to confirmed pitches. Returns (hits, warnings)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return hits, ["llm_confirm is on but ANTHROPIC_API_KEY is not set; kept keyword hits"]

    kept: list[Hit] = []
    warnings: list[str] = []
    for hit in hits:
        activity = activities.get(hit.activity_id)
        if activity is None:
            kept.append(hit)
            continue

        prompt = _PROMPT.format(
            name=activity.name,
            description=activity.description or activity.name,
            excerpt=window_text(cues, hit.start, hit.end),
        )
        try:
            verdict = _parse_verdict(_call(cfg.llm_model, prompt, api_key))
        except LLMUnavailable as exc:
            warnings.append(f"{hit.activity_id}: LLM call failed ({exc}); kept keyword hit")
            kept.append(hit)
            continue

        if verdict is None:
            warnings.append(f"{hit.activity_id}: unparseable LLM reply; kept keyword hit")
            kept.append(hit)
            continue

        if not verdict.get("is_pitch"):
            continue

        refined = _to_seconds(str(verdict.get("start", "")))
        if refined is not None:
            hit.start = refined
        hit.quote = str(verdict.get("quote") or hit.quote)[:400]
        hit.confidence = str(verdict.get("confidence") or "")
        hit.method = "keyword+llm"
        kept.append(hit)

    return kept, warnings
