import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import polito_sync as ps  # noqa: E402

TREE = [
    {"type": "directory", "id": "1", "name": "Week 1", "files": [
        {"type": "file", "id": "10", "name": "Lecture1.pdf", "mimeType": "application/pdf",
         "sizeInKiloBytes": 2048, "checksum": "aaa"},
        {"type": "file", "id": "11", "name": "lesson.mp4", "mimeType": "video/mp4",
         "sizeInKiloBytes": 100000, "checksum": "bbb"},
    ]},
    {"type": "file", "id": "12", "name": 'bad:name?.txt', "mimeType": "text/plain",
     "sizeInKiloBytes": 1, "checksum": "ccc"},
]


class FakeApi:
    def __init__(self, tree):
        self.tree = tree
        self.downloaded = []

    def courses(self):
        return [{"id": 7, "name": "Fisica 1", "isInPersonalStudyPlan": True},
                {"id": 9, "name": "Chimica", "isInPersonalStudyPlan": True},   # no local folder
                {"id": 8, "name": "Other", "isInPersonalStudyPlan": False}]

    def files(self, course_id):
        return self.tree

    def download(self, course_id, file_id, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("x")
        self.downloaded.append((course_id, file_id))


def make_cfg(tmp):
    cfg = ps.Config.__new__(ps.Config)
    cfg.download_dir = Path(tmp) / "dl"
    cfg.state_dir = Path(tmp) / "state"
    cfg.skip_mime = ("video/", "audio/")
    cfg.max_size_mb = 200
    cfg.only_study_plan = True
    cfg.new_subdir = "New"
    cfg.create_missing = False
    cfg.course_map = {}
    (cfg.download_dir / "FISICA 1").mkdir(parents=True)  # loose name match
    return cfg


class SyncTests(unittest.TestCase):
    def test_downloads_missing_into_new_then_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, api = make_cfg(tmp), FakeApi(TREE)
            first = ps.sync(api, cfg)
            self.assertEqual(sorted(api.downloaded), [(7, "10"), (7, "12")])  # video skipped, Chimica skipped
            self.assertEqual(len(first), 2)
            course = cfg.download_dir / "FISICA 1"
            self.assertTrue((course / "New" / "Week 1" / "Lecture1.pdf").exists())
            self.assertTrue((course / "New" / "bad_name_.txt").exists())
            self.assertFalse((cfg.download_dir / "Chimica").exists())
            api.downloaded.clear()
            self.assertEqual(ps.sync(api, cfg), [])
            self.assertEqual(api.downloaded, [])

    def test_existing_local_file_is_not_downloaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, api = make_cfg(tmp), FakeApi(TREE)
            mine = cfg.download_dir / "FISICA 1" / "My sorting" / "Lecture1[1].pdf"
            mine.parent.mkdir(parents=True)
            mine.write_text("mine")
            ps.sync(api, cfg)
            self.assertEqual(api.downloaded, [(7, "12")])
            self.assertEqual(mine.read_text(), "mine")  # untouched

    def test_course_map_and_root_subdir(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, api = make_cfg(tmp), FakeApi(TREE)
            cfg.course_map = {"Chimica": "Chemistry"}
            cfg.new_subdir = ""
            ps.sync(api, cfg)
            self.assertTrue((cfg.download_dir / "Chemistry" / "Week 1" / "Lecture1.pdf").exists())

    def test_changed_checksum_redownloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, api = make_cfg(tmp), FakeApi(TREE)
            ps.sync(api, cfg)
            api.downloaded.clear()
            api.tree = [{**TREE[0], "files": [{**TREE[0]["files"][0], "checksum": "zzz"}]}, TREE[1]]
            ps.sync(api, cfg)
            self.assertEqual(api.downloaded, [(7, "10")])

    def test_init_only_records_without_downloading(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, api = make_cfg(tmp), FakeApi(TREE)
            ps.sync(api, cfg, init_only=True)
            self.assertEqual(api.downloaded, [])
            self.assertEqual(ps.sync(api, cfg), [])

    def test_dry_run_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, api = make_cfg(tmp), FakeApi(TREE)
            ps.sync(api, cfg, dry_run=True)
            self.assertEqual(api.downloaded, [])
            self.assertFalse((cfg.state_dir / "state.json").exists())

    def test_helpers(self):
        self.assertEqual(ps.safe_name('a:b/c?'), "a_b_c_")
        self.assertEqual(ps.safe_name("..."), "unnamed")
        self.assertEqual(ps.file_key("Slides[1].pdf"), ps.file_key("slides.pdf"))
        self.assertEqual(ps.file_key("Slides (2).pdf"), "slides.pdf")
        self.assertEqual(ps.norm("Propulsion Systems & their..."), "propulsionsystemstheir")


class NoticeApi(FakeApi):
    def __init__(self, notices):
        super().__init__(TREE)
        self.by_course = notices

    def notices(self, course_id):
        return self.by_course.get(course_id, [])


def notice(nid, text, published="2026-11-10T09:00:00Z", course="Fisica 1", cid=7):
    return {"id": nid, "course": course, "courseId": cid, "publishedAt": published, "text": text}


class NoticeTests(unittest.TestCase):
    def test_html_to_text_and_links(self):
        text, links = ps.html_to_text('<p>Hello&nbsp;<b>all</b></p><ul><li>one</li><li>two</li></ul>'
                                      '<p>See <a href="https://polito.it/x">here</a></p>')
        self.assertEqual(text, "Hello all\n\n• one\n\n• two\n\nSee here")
        self.assertEqual(links, ["https://polito.it/x"])

    def test_fetch_notices_marks_new_after_first_fetch(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(tmp)
            raw = {7: [{"id": 1, "publishedAt": "2026-11-01T10:00:00Z", "expiresAt": None, "content": "<p>A</p>"}],
                   9: [{"id": 2, "publishedAt": "2026-11-03T10:00:00Z", "expiresAt": None, "content": "<p>B</p>"}],
                   8: [{"id": 3, "publishedAt": "2026-11-04T10:00:00Z", "expiresAt": None, "content": "x"}]}
            api = NoticeApi(raw)
            first = ps.fetch_notices(api, cfg)
            self.assertEqual([n["id"] for n in first], [2, 1])  # newest first; course 8 not in study plan
            self.assertFalse(any(n["new"] for n in first))       # first fetch is a baseline
            raw[7].append({"id": 5, "publishedAt": "2026-11-05T10:00:00Z", "expiresAt": None, "content": "C"})
            second = ps.fetch_notices(api, cfg)
            self.assertEqual({n["id"]: n["new"] for n in second}, {5: True, 2: False, 1: False})
            cached, at = ps.load_cached_notices(cfg)
            self.assertEqual(len(cached), 3)
            self.assertIsNotNone(at)

    def test_find_dates_formats(self):
        ref = ps.date(2026, 11, 10)
        d = lambda s: [x[0] for x in ps.find_dates(s, ref)]  # noqa: E731
        self.assertEqual(d("on 18/11 at 14:30"), [ps.date(2026, 11, 18)])
        self.assertEqual(d("il 3.12.2026 ore 10"), [ps.date(2026, 12, 3)])
        self.assertEqual(d("2026-12-01"), [ps.date(2026, 12, 1)])
        self.assertEqual(d("Thursday, November 20th"), [ps.date(2026, 11, 20)])
        self.assertEqual(d("giovedì 15 gennaio"), [ps.date(2027, 1, 15)])  # rolls into next year
        self.assertEqual(d("the 2nd of Dec 2026"), [ps.date(2026, 12, 2)])
        self.assertEqual(d("version 14.30 and score 7/30"), [])  # no fake dates
        self.assertEqual(ps.find_time("from 2 pm"), "14:00")
        self.assertEqual(ps.find_time("ore 9.15"), "09:15")

    def test_extract_events_and_heads_up(self):
        today = ps.date(2026, 11, 16)
        notices = [
            notice(1, "Dear students,\nOn 20 November at 15:00 there will be a seminar by a guest speaker "
                      "from ESA in room 1P.\nRegards"),
            notice(2, "The lecture of 18/11 is cancelled.", course="Chimica", cid=9),
            notice(3, "The midterm exam was on 3 November.", published="2026-10-20T09:00:00Z"),
            notice(4, "The deadline for the lab report has been extended, see the portal.",
                   published="2026-11-14T09:00:00Z"),
            notice(5, "New slides uploaded.", published="2026-11-15T09:00:00Z"),
        ]
        events, heads = ps.extract_events(notices, today)
        self.assertEqual([(e["notice_id"], e["date"], e["kind"]) for e in events],
                         [(2, ps.date(2026, 11, 18), "Class change"),
                          (1, ps.date(2026, 11, 20), "Seminar / talk")])
        self.assertEqual(events[1]["time"], "15:00")
        self.assertIn("ESA", events[1]["snippet"])
        self.assertEqual([(h["notice_id"], h["kind"]) for h in heads], [(4, "Deadline")])
        groups = ps.group_events(events, today)
        self.assertEqual([g[0] for g in groups], ["Next 7 days"])


if __name__ == "__main__":
    unittest.main()
