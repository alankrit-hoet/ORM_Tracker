import pytest

from orm_tracker.transcript import TranscriptError, format_timestamp, parse

VTT = """WEBVTT

1
00:00:05.000 --> 00:00:09.000
Ashutosh Goel: Welcome everyone to today's session.

2
00:12:30.500 --> 00:12:38.000
Ashutosh Goel: Before we start, please log in to the LMS.
"""

SRT = """1
00:00:05,000 --> 00:00:09,000
Welcome everyone.

2
01:02:03,000 --> 01:02:09,000
Nisha: Post this on LinkedIn and tag us.
"""

PLAIN = """00:00:05 Ashutosh: Welcome everyone.
[00:10:00] Ashutosh: Drop a Google review for us.
"""


def test_parses_vtt_with_speakers():
    cues = parse(VTT)
    assert len(cues) == 2
    assert cues[0].start == 5.0
    assert cues[0].speaker == "Ashutosh Goel"
    assert cues[1].start == 750.5
    assert "log in to the LMS" in cues[1].text


def test_parses_srt_and_hours():
    cues = parse(SRT)
    assert cues[1].start == 3723.0
    assert cues[1].speaker == "Nisha"


def test_parses_leading_timestamps_and_infers_end():
    cues = parse(PLAIN)
    assert [c.start for c in cues] == [5.0, 600.0]
    assert cues[0].end == 600.0


def test_untimestamped_transcript_is_an_error_not_an_empty_result():
    with pytest.raises(TranscriptError):
        parse("Ashutosh: welcome everyone\nNisha: thanks\n")


def test_colon_inside_a_sentence_is_not_a_speaker():
    (cue,) = parse("00:00:01 so here is the thing: we use the LMS\n")
    assert cue.speaker == ""
    assert cue.text.startswith("so here is the thing")


def test_format_timestamp():
    assert format_timestamp(0) == "00:00:00"
    assert format_timestamp(3723.9) == "01:02:03"


def test_cues_are_sorted_by_start():
    cues = parse("00:05:00 second line\n00:01:00 first line\n")
    assert [c.start for c in cues] == [60.0, 300.0]
