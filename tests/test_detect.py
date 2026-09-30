from orm_tracker.config import Activity, DetectionConfig
from orm_tracker.detect import scan
from orm_tracker.transcript import Cue

LMS = Activity(
    id="lms_adoption",
    name="LMS Adoption",
    strong_keywords=("lms", "learning portal"),
    support_keywords=("log in", "dashboard", "assignment"),
)
REVIEW = Activity(
    id="google_review",
    name="Google Review",
    strong_keywords=("google review", "5 star"),
    support_keywords=("rate us", "do me a favour"),
    exclude_keywords=("quick review of",),
)
CFG = DetectionConfig(window_seconds=60, min_score=2.0, merge_gap_seconds=120)


def cue(start, text, speaker="Trainer"):
    return Cue(start, start + 5, speaker, text)


def test_finds_pitch_and_reports_its_start():
    cues = [
        cue(0, "Welcome everyone to the session."),
        cue(600, "Please log in to the LMS and open your dashboard."),
    ]
    (hit,) = scan(cues, [LMS], CFG)
    assert hit.activity_id == "lms_adoption"
    assert hit.timestamp == "00:10:00"
    assert "lms" in hit.matched


def test_strong_keyword_is_required():
    cues = [cue(0, "Please log in and check your dashboard and assignment.")]
    assert scan(cues, [LMS], CFG) == []


def test_exclude_keyword_suppresses_the_window():
    cues = [cue(0, "Let's do a quick review of that, then a 5 star recap.")]
    assert scan(cues, [REVIEW], CFG) == []


def test_nearby_mentions_merge_into_one_pitch():
    cues = [
        cue(300, "Open the LMS now, log in please."),
        cue(340, "Again, the LMS dashboard, log in."),
    ]
    hits = scan(cues, [LMS], CFG)
    assert len(hits) == 1
    assert hits[0].timestamp == "00:05:00"


def test_distant_mentions_stay_separate():
    cues = [
        cue(300, "Open the LMS, log in please."),
        cue(3000, "Reminder: the LMS assignment is due, log in."),
    ]
    hits = scan(cues, [LMS], CFG)
    assert [h.timestamp for h in hits] == ["00:05:00", "00:50:00"]


def test_report_first_keeps_only_the_earliest():
    cues = [
        cue(300, "Open the LMS, log in please."),
        cue(3000, "Reminder: the LMS assignment is due, log in."),
    ]
    hits = scan(cues, [LMS], DetectionConfig(window_seconds=60, report="first"))
    assert [h.timestamp for h in hits] == ["00:05:00"]


def test_activities_are_detected_independently():
    cues = [
        cue(60, "Log in to the LMS, check the dashboard."),
        cue(1800, "Do me a favour and leave a google review, rate us."),
    ]
    hits = scan(cues, [LMS, REVIEW], CFG)
    assert {h.activity_id: h.timestamp for h in hits} == {
        "lms_adoption": "00:01:00",
        "google_review": "00:30:00",
    }


def test_keywords_match_whole_words_only():
    cues = [cue(0, "Fill in the form and log in to the dashboard.")]
    orm = Activity(id="x", name="X", strong_keywords=("orm",), support_keywords=("log in",))
    assert scan(cues, [orm], CFG) == []


def test_pitch_split_across_cues_still_scores():
    cues = [
        cue(100, "One more thing before we wrap up."),
        cue(110, "Head over to the LMS."),
        cue(120, "Log in there and finish the assignment."),
    ]
    (hit,) = scan(cues, [LMS], CFG)
    assert hit.timestamp == "00:01:50"


def test_quote_comes_from_the_cue_with_the_strong_keyword():
    cues = [
        cue(100, "Alright, quick housekeeping, log in somewhere."),
        cue(120, "Specifically the LMS, please."),
    ]
    (hit,) = scan(cues, [LMS], CFG)
    assert "LMS" in hit.quote
