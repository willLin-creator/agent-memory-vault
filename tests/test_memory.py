#!/usr/bin/env python3
"""Tests for the coldness signal (memory-reindex.py) and the touch writer (memory-touch.py).

Stdlib unittest only, to match the repo's no-dependencies stance. Run with any of:
    python3 tests/test_memory.py
    python3 -m unittest discover -s tests
"""

import importlib.util
import os
import pathlib
import tempfile
import unittest
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(mod_name, filename):
    spec = importlib.util.spec_from_file_location(mod_name, ROOT / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


reindex = _load("memory_reindex", "memory-reindex.py")
touch = _load("memory_touch", "scripts/memory-touch.py")

TODAY = date(2026, 1, 1)  # fixed "now" so recency math is deterministic


def fm(**meta):
    """Build a parsed-frontmatter dict with everything under metadata:, like the real parser."""
    return {"metadata": dict(meta)}


class TestIsCold(unittest.TestCase):
    def test_disused_low_importance_is_cold(self):
        reason = reindex.is_cold(fm(last_accessed="2020-01-01", access_count="0"), TODAY)
        self.assertIsNotNone(reason)
        self.assertIn("since access", reason)

    def test_recently_accessed_is_not_cold(self):
        # 17 days before TODAY, well under the 90-day recency floor
        self.assertIsNone(reindex.is_cold(fm(last_accessed="2025-12-15", access_count="0"), TODAY))

    def test_no_last_accessed_is_ignored(self):
        # opt-in: without a usage signal there is nothing to weigh
        self.assertIsNone(reindex.is_cold(fm(access_count="0"), TODAY))

    def test_pinned_is_exempt(self):
        self.assertIsNone(
            reindex.is_cold(fm(last_accessed="2020-01-01", access_count="0", enforcement="pinned"), TODAY)
        )

    def test_hook_is_exempt(self):
        self.assertIsNone(
            reindex.is_cold(fm(last_accessed="2020-01-01", access_count="0", enforcement="hook"), TODAY)
        )

    def test_high_importance_is_exempt(self):
        self.assertIsNone(
            reindex.is_cold(fm(last_accessed="2020-01-01", access_count="0", importance="8"), TODAY)
        )

    def test_low_importance_still_cold_and_reported(self):
        reason = reindex.is_cold(fm(last_accessed="2020-01-01", access_count="0", importance="3"), TODAY)
        self.assertIsNotNone(reason)
        self.assertIn("importance 3", reason)

    def test_frequently_accessed_is_exempt(self):
        # access_count above COLD_MAX_HITS (default 1) means it is still in use
        self.assertIsNone(
            reindex.is_cold(fm(last_accessed="2020-01-01", access_count="5"), TODAY)
        )

    def test_top_level_fields_are_read(self):
        # fields may sit at the top level instead of under metadata:
        self.assertIsNotNone(reindex.is_cold({"last_accessed": "2020-01-01", "metadata": {}}, TODAY))


class TestAuditWiring(unittest.TestCase):
    def _vault(self, files):
        d = tempfile.mkdtemp()
        for name, body in files.items():
            with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                f.write(body)
        return d

    def _audit(self, d):
        reindex.MEM_DIR = d
        reindex.INDEX = os.path.join(d, "MEMORY.md")
        return reindex.audit()

    def test_cold_reported_but_does_not_gate_exit_code(self):
        index = "# Memory\n- cold demo (`reference_cold_demo.md`)\n"
        cold = (
            "---\nname: reference_cold_demo\n"
            "description: A memory gone cold by disuse.\n"
            "metadata:\n  type: reference\n  last_accessed: 2020-01-01\n  access_count: 0\n---\nBody.\n"
        )
        r = self._audit(self._vault({"MEMORY.md": index, "reference_cold_demo.md": cold}))
        self.assertIn("reference_cold_demo.md", [c[0] for c in r["cold_candidates"]])
        # coldness is a hint, so the only issue being cold must NOT recommend action
        self.assertFalse(r["action_recommended"])

    def test_hard_stale_is_not_also_listed_cold(self):
        index = "# Memory\n- done thing (`project_done.md`)\n"
        done = (
            "---\nname: project_done\n"
            "description: A finished project.\n"
            "metadata:\n  type: project\n  status: done\n  last_accessed: 2020-01-01\n  access_count: 0\n---\nBody.\n"
        )
        r = self._audit(self._vault({"MEMORY.md": index, "project_done.md": done}))
        stale_files = [s[0] for s in r["stale_candidates"]]
        cold_files = [c[0] for c in r["cold_candidates"]]
        self.assertIn("project_done.md", stale_files)
        self.assertNotIn("project_done.md", cold_files)  # stale wins; not double-listed
        self.assertTrue(r["action_recommended"])  # stale DOES gate


class TestTouch(unittest.TestCase):
    def _write(self, body):
        fd, p = tempfile.mkstemp(suffix=".md")
        os.close(fd)
        with open(p, "w", encoding="utf-8") as f:
            f.write(body)
        return p

    def test_adds_fields_when_absent(self):
        p = self._write("---\nname: reference_x\ndescription: d\nmetadata:\n  type: reference\n---\nBody.\n")
        self.assertEqual(touch.main(["--date", "2026-07-10", p]), 0)
        out = pathlib.Path(p).read_text()
        self.assertIn("last_accessed: 2026-07-10", out)
        self.assertIn("access_count: 1", out)
        self.assertIn("Body.", out)  # body preserved

    def test_increments_existing_count_and_updates_date(self):
        p = self._write(
            "---\nname: reference_x\ndescription: d\n"
            "metadata:\n  last_accessed: 2020-01-01\n  access_count: 4\n---\nBody.\n"
        )
        touch.main(["--date", "2026-07-10", p])
        out = pathlib.Path(p).read_text()
        self.assertIn("access_count: 5", out)
        self.assertIn("last_accessed: 2026-07-10", out)
        self.assertNotIn("2020-01-01", out)  # old date replaced in place, not duplicated

    def test_creates_metadata_block_when_absent(self):
        p = self._write("---\nname: reference_x\ndescription: d\n---\nBody.\n")
        touch.main(["--date", "2026-07-10", p])
        out = pathlib.Path(p).read_text()
        self.assertIn("metadata:", out)
        self.assertIn("access_count: 1", out)

    def test_no_frontmatter_is_error_and_no_write(self):
        p = self._write("no frontmatter here\n")
        before = pathlib.Path(p).read_text()
        self.assertEqual(touch.main(["--date", "2026-07-10", p]), 2)
        self.assertEqual(pathlib.Path(p).read_text(), before)  # untouched

    def test_dry_run_does_not_write(self):
        body = "---\nname: reference_x\ndescription: d\nmetadata:\n  type: reference\n---\nBody.\n"
        p = self._write(body)
        touch.main(["--dry-run", "--date", "2026-07-10", p])
        self.assertEqual(pathlib.Path(p).read_text(), body)  # unchanged on disk

    def test_touched_file_reparses_and_is_no_longer_cold(self):
        # end-to-end: a cold file, once touched today, stops being cold
        p = self._write(
            "---\nname: reference_x\ndescription: d\n"
            "metadata:\n  last_accessed: 2020-01-01\n  access_count: 0\n---\nBody.\n"
        )
        touch.main(["--date", date.today().isoformat(), p])
        parsed = reindex.parse_frontmatter(pathlib.Path(p).read_text())
        self.assertIsNone(reindex.is_cold(parsed, date.today()))


if __name__ == "__main__":
    unittest.main()
