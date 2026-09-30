from dataclasses import dataclass

from orm_tracker import check
from orm_tracker.config import Activity, Config, DetectionConfig, DriveConfig, SheetConfig

VTT = """WEBVTT

1
00:10:00.000 --> 00:10:06.000
Nandini: Please log in to the LMS and finish the assignment.
"""

NO_TIMESTAMPS = "Nandini: please log in to the LMS\nLearner: ok\n"


@dataclass
class FakeFolder:
    id: str
    name: str
    date: str = ""
    batch: str = ""
    title: str = ""


@dataclass
class FakeFile:
    id: str
    name: str


class FakeDrive:
    def __init__(self, folders, skipped=(), transcripts=None, raise_on_list=None):
        self._folders = folders
        self._skipped = list(skipped)
        self._transcripts = transcripts or {}
        self._raise = raise_on_list

    def session_folders(self, cfg):
        if self._raise:
            raise self._raise
        return self._folders, self._skipped

    def find_transcript(self, folder_id, hints):
        entry = self._transcripts.get(folder_id)
        return FakeFile(f"f-{folder_id}", entry[0]) if entry else None

    def read_text(self, tfile):
        for name, body in self._transcripts.values():
            if name == tfile.name:
                return body
        raise AssertionError("unexpected read")


def make_config(spreadsheet_id=""):
    return Config(
        drive=DriveConfig(
            root_folder_id="ROOT",
            folder_name_pattern=r"^(?P<date>[^-]+)-(?P<batch>[^-]+)-(?P<title>.+)$",
            transcript_name_hints=(".vtt",),
        ),
        sheet=SheetConfig(spreadsheet_id=spreadsheet_id),
        detection=DetectionConfig(),
        activities=(Activity(id="lms", name="LMS", strong_keywords=("lms",)),),
    )


def statuses(results):
    return [r.status for r in results]


def test_unreachable_folder_says_membership_not_just_sharing():
    drive = FakeDrive([], raise_on_list=PermissionError("404 File not found: ROOT"))
    (result,) = check.run(drive, make_config())
    assert result.status == check.FAIL
    assert "MEMBER" in result.detail
    assert "ROOT" in result.label


def test_healthy_setup_has_no_failures():
    folders = [FakeFolder("a", "27th Sep-B41-Prompt Engineering")]
    drive = FakeDrive(folders, transcripts={"a": ("session.vtt", VTT)})
    results = check.run(drive, make_config())
    assert check.FAIL not in statuses(results)
    assert any("1 timestamped cues" in (r.detail or "") for r in results)


def test_folders_present_but_none_match_the_pattern_is_a_failure():
    drive = FakeDrive([], skipped=["Recording 2026-09-27", "misc"])
    results = check.run(drive, make_config())
    assert check.FAIL in statuses(results)
    assert any("naming pattern" in r.label for r in results)


def test_untimestamped_transcript_is_reported_as_a_failure():
    folders = [FakeFolder("a", "27th Sep-B41-Prompt Engineering")]
    drive = FakeDrive(folders, transcripts={"a": ("notes.vtt", NO_TIMESTAMPS)})
    results = check.run(drive, make_config())
    assert check.FAIL in statuses(results)
    assert any("would report every activity as Not Detected" in (r.detail or "")
               for r in results)


def test_missing_transcript_warns_but_does_not_fail_when_another_works():
    folders = [
        FakeFolder("a", "27th Sep-B41-One"),
        FakeFolder("b", "27th Sep-B41-Two"),
    ]
    drive = FakeDrive(folders, transcripts={"a": ("session.vtt", VTT)})
    results = check.run(drive, make_config())
    assert check.FAIL not in statuses(results)
    assert check.WARN in statuses(results)


def test_no_spreadsheet_configured_warns():
    folders = [FakeFolder("a", "27th Sep-B41-One")]
    drive = FakeDrive(folders, transcripts={"a": ("session.vtt", VTT)})
    results = check.run(drive, make_config(), sheet_writer=None)
    assert any("no sheet.spreadsheet_id" in r.label for r in results)


def test_unwritable_sheet_fails_and_names_the_remedy():
    class Unwritable:
        def probe(self):
            raise PermissionError("caller does not have permission")

    folders = [FakeFolder("a", "27th Sep-B41-One")]
    drive = FakeDrive(folders, transcripts={"a": ("session.vtt", VTT)})
    results = check.run(drive, make_config("SHEET"), sheet_writer=Unwritable())
    failure = next(r for r in results if r.status == check.FAIL)
    assert "Editor" in failure.detail


def test_report_exit_code_reflects_failures():
    assert check.report([check.Result(check.OK, "fine")]) == 0
    assert check.report([check.Result(check.FAIL, "broken")]) == 1
