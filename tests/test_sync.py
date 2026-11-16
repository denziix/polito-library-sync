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


if __name__ == "__main__":
    unittest.main()
