# ORM Activity Tracker

Reads the transcript of every session in a Google Drive folder, finds the point
where each ORM activity was pitched, and keeps the result as a row per
session × activity in a Google Sheet. Re-running picks up only what changed.

```
Drive folder                 transcript              detection              Google Sheet
<date>-<batch>-<title>/  ->  .vtt / .srt / Doc  ->   keywords (+ LLM)  ->   one row per pitch
```

## What counts as an ORM activity

Whatever you put in `config.yaml`. The seeded list mirrors the values already
used in the org's *Session Details* sheet — `lms adoption`, `linkedin orm`,
`Win of the week`, plus review and referral asks. Each activity is:

```yaml
- id: lms_adoption
  name: "LMS Adoption"
  description: >
    The trainer asks learners to log in to, open, or complete work on the LMS.
  strong_keywords: ["lms", "learning portal"]      # one is REQUIRED to match
  support_keywords: ["log in", "dashboard"]        # raises confidence only
  exclude_keywords: []                             # kills the match outright
```

`config.yaml` is the tracker's logic, so it is version-controlled and reviewable.
Credentials never go in it.

## How detection works, and where it is weak

**Stage 1 — keywords.** Cues are grouped into rolling 90-second windows. A
window scores `2.0` per distinct strong keyword and `0.5` per support keyword;
it must clear `min_score` **and** contain at least one strong keyword. Matching
is whole-word, so `orm` never fires on `form`. Nearby windows merge into one
pitch, timestamped at the cue where the activity is actually named.

This stage is tuned for recall, and on its own it will over-report. A training
session is full of the words "post", "review", "share" and "link" used for
reasons that have nothing to do with ORM. The strong/support split and
`exclude_keywords` hold most of that back, but not all of it.

**Stage 2 — LLM confirmation (optional, off by default).** Set
`detection.llm_confirm: true` and export `ANTHROPIC_API_KEY`. Each stage-1
candidate is sent to Claude with the surrounding transcript, which decides
whether the trainer is genuinely pitching the activity and refines the start
timestamp. This is what converts recall into precision. If the key is missing
or the call fails, candidates pass through flagged as keyword-only — a bad key
degrades precision, it never silently loses a session.

**What the tracker cannot do:** a transcript with no timestamps cannot answer
"when". Rather than return an empty result that looks identical to "the trainer
never pitched it", the parser raises and the session is reported as skipped.

## Setup

1. **Service account.** Create one in Google Cloud, enable the Drive and Sheets
   APIs, download the JSON key.
2. **Grant it access.** Add the service account's email as a **Viewer** on the
   Drive folder (for a Shared Drive, add it as a member) and as an **Editor**
   on the target Sheet. Nothing works until this is done — the account that
   authorises the API is not your account.
3. **Fill in `config.yaml`**: `drive.root_folder_id` and `sheet.spreadsheet_id`.
4. Install and run:

```bash
pip install -r requirements.txt
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
python -m orm_tracker.cli
```

## Running it

```bash
# Normal run: only sessions whose transcript is new or changed.
python -m orm_tracker.cli

# Reprocess everything (after editing keywords).
python -m orm_tracker.cli --full

# Tune keywords against transcripts on disk. No credentials, no Google SDK.
python -m orm_tracker.cli --local-dir ./transcripts

# Write a CSV instead of touching the Sheet.
python -m orm_tracker.cli --csv-only --csv out/orm_tracker.csv
```

| Flag | Effect |
| --- | --- |
| `--config` | config file (default `config.yaml`) |
| `--folder` | override the Drive folder; accepts an id or a Drive URL |
| `--local-dir` | scan transcript files in a directory instead of Drive |
| `--full` | ignore `state.json` and reprocess every session |
| `--no-state` | do not write `state.json` |
| `--csv-only` / `--csv` | skip the Sheet; write a CSV |

## Keeping the Sheet in step with Drive

The Drive folder grows, so the tracker is designed to be run repeatedly:

- **Incremental.** `state.json` records each session's transcript id and
  modified time. Unchanged sessions are skipped.
- **Idempotent.** Every row carries
  `Key = <folder id>|<activity id>|<timestamp>`. A rerun overwrites the row
  with that key rather than appending a duplicate, so re-running after
  tightening keywords corrects the record in place.
- **Scheduled.** `.github/workflows/orm-tracker.yml` runs it Monday mornings
  IST. Add repository secrets `GOOGLE_SERVICE_ACCOUNT_JSON` and, if you enable
  stage 2, `ANTHROPIC_API_KEY`.

Rows are never deleted. An activity with no detected pitch is written as a
`Detected = No` row, so "we checked and it did not happen" is distinguishable
from "we never looked at this session".

## Sheet columns

`Key`, `Date`, `Batch`, `Session Title`, `ORM Activity`, `Detected`,
`Timestamp`, `Timestamp (sec)`, `Quote`, `Speaker`, `Matched Keywords`,
`Confidence`, `Method`, `Session Folder`, `Transcript File`, `Last Updated`.

`Quote` and `Matched Keywords` exist so a reviewer can sanity-check a row
without opening the recording. `Timestamp (sec)` is there for sorting and for
building a deep link into the video.

## Tests

```bash
pip install pytest PyYAML
python -m pytest tests -q
```

## Layout

| File | Role |
| --- | --- |
| `config.py` | load and validate `config.yaml` |
| `transcript.py` | VTT / SRT / plain-text → timestamped cues |
| `detect.py` | keyword windows → candidate pitches |
| `llm.py` | optional Claude confirmation pass |
| `drive.py` | enumerate session folders, fetch transcripts (Shared Drive aware) |
| `sheets.py` | upsert rows by key |
| `rows.py` | the output row schema |
| `cli.py` | wiring, incremental state, CSV fallback |
