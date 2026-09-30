# ORM Activity Tracker

Give it a session transcript. It tells you, for each ORM activity, the
timestamp where the trainer pitched it — and the line that triggered the match,
so you can verify it at a glance.

No Google account, no Sheet, no setup. You feed transcripts in by hand.

```bash
pip install PyYAML

python -m orm_tracker.cli transcript.vtt          # a file
pbpaste | python -m orm_tracker.cli -             # pasted / piped in
python -m orm_tracker.cli transcript.vtt --json   # machine-readable
```

Example:

```
LMS Adoption:
  00:41:10  [assignment, dashboard, lms, log in]
      Nandini: One quick thing before the break. Please log in to the LMS today itself.
  01:28:15  [lms, log in]
      Nandini: Last thing, the LMS again, please log in before Wednesday.

LinkedIn ORM:
  01:12:30  [certificate, linkedin, post, tag the page]
      Nandini: Do me a favour. Post about today on LinkedIn, tag the page.

Win of the Week: not detected
Google Review / Rating: not detected
```

## The ORM activities are yours to define

Everything lives in `config.yaml`. Each activity:

```yaml
- id: lms_adoption
  name: "LMS Adoption"
  strong_keywords: ["lms", "learning portal"]   # one is REQUIRED to match
  support_keywords: ["log in", "dashboard"]      # raise confidence only
  exclude_keywords: []                           # kill the match outright
```

The seeded list mirrors the ORM values already used in the org's *Session
Details* sheet (`lms adoption`, `linkedin orm`, `Win of the week`) plus review
and referral asks. **Replace them with your real list** — this keyword file is
the entire detection logic.

## How it decides

Cues are grouped into rolling 90-second windows. A window scores `2.0` per
distinct strong keyword and `0.5` per support keyword; it must clear `min_score`
**and** contain at least one strong keyword. Matching is whole-word, so `orm`
never fires on `form`. Nearby matches merge into one pitch, timestamped at the
line where the activity is actually named.

This is tuned for recall, so it can over-report — "review" and "post" show up in
a training session for reasons unrelated to ORM. The strong/support split and
`exclude_keywords` hold most of that back; the `[matched keywords]` and quote on
every line let you spot the rest. If you want it stricter, add
`--llm` (needs `ANTHROPIC_API_KEY`): each match is sent to Claude with the
surrounding transcript to confirm it's a real pitch.

## Transcript formats

WebVTT (`.vtt`), SubRip (`.srt`), and plain text with `HH:MM:SS` at the start of
lines. Zoom and Google Meet both export `.vtt`.

**The transcript must carry per-line timestamps.** A Meet transcript saved as a
plain summary has none, and no tool can invent them — the CLI says so and exits
rather than pretending nothing was pitched.

## Tests

```bash
pip install pytest PyYAML
python -m pytest tests -q
```

## Layout

| File | Role |
| --- | --- |
| `config.py` | load `config.yaml` (activities + thresholds) |
| `transcript.py` | VTT / SRT / plain text → timestamped cues |
| `detect.py` | keyword windows → pitches with timestamps |
| `llm.py` | optional `--llm` confirmation pass |
| `cli.py` | transcript in, timestamps out |
