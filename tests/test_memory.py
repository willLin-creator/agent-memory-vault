#!/usr/bin/env python3
"""Tests for the coldness signal (memory-reindex.py), the touch writer (memory-touch.py),
the index generator (memory-index.py), and the two hooks.

Stdlib unittest only, to match the repo's no-dependencies stance. Run with any of:
    python3 tests/test_memory.py
    python3 -m unittest discover -s tests
"""

import importlib.util
import io
import os
import pathlib
import sys
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
hook = _load("recall_touch", "hooks/recall-touch.py")
indexer = _load("memory_index", "memory-index.py")

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


class TestRecallHook(unittest.TestCase):
    def setUp(self):
        self.vault = tempfile.mkdtemp()
        self.note = os.path.join(self.vault, "reference_x.md")
        with open(self.note, "w", encoding="utf-8") as f:
            f.write("---\nname: reference_x\ndescription: d\nmetadata:\n  type: reference\n---\nBody.\n")

    def _payload(self, path, tool="Read"):
        return {"tool_name": tool, "tool_input": {"file_path": path}}

    def test_vault_md_read_is_targeted(self):
        self.assertEqual(hook.target_path(self._payload(self.note), self.vault), os.path.realpath(self.note))

    def test_file_outside_vault_ignored(self):
        outside = os.path.join(tempfile.mkdtemp(), "reference_y.md")
        self.assertIsNone(hook.target_path(self._payload(outside), self.vault))

    def test_non_read_tool_ignored(self):
        self.assertIsNone(hook.target_path(self._payload(self.note, tool="Edit"), self.vault))

    def test_non_md_ignored(self):
        other = os.path.join(self.vault, "notes.txt")
        self.assertIsNone(hook.target_path(self._payload(other), self.vault))

    def test_index_file_ignored(self):
        idx = os.path.join(self.vault, "MEMORY.md")
        self.assertIsNone(hook.target_path(self._payload(idx), self.vault))

    def test_no_vault_env_ignored(self):
        self.assertIsNone(hook.target_path(self._payload(self.note), None))

    def _run_main(self, stdin_text, env_vault):
        old_stdin, old_env = sys.stdin, os.environ.get("AGENT_MEMORY_DIR")
        sys.stdin = io.StringIO(stdin_text)
        if env_vault is None:
            os.environ.pop("AGENT_MEMORY_DIR", None)
        else:
            os.environ["AGENT_MEMORY_DIR"] = env_vault
        try:
            return hook.main()
        finally:
            sys.stdin = old_stdin
            if old_env is None:
                os.environ.pop("AGENT_MEMORY_DIR", None)
            else:
                os.environ["AGENT_MEMORY_DIR"] = old_env

    def test_main_stamps_the_read_file(self):
        import json
        rc = self._run_main(json.dumps(self._payload(self.note)), self.vault)
        self.assertEqual(rc, 0)
        out = pathlib.Path(self.note).read_text()
        self.assertIn("access_count: 1", out)
        self.assertIn("last_accessed:", out)

    def test_main_malformed_json_exits_zero_and_writes_nothing(self):
        before = pathlib.Path(self.note).read_text()
        self.assertEqual(self._run_main("not json{", self.vault), 0)
        self.assertEqual(pathlib.Path(self.note).read_text(), before)



class TestIndexGenerator(unittest.TestCase):
    """memory-index.py: the generated pointer block."""

    NOTE = "---\nname: {name}\ndescription: {desc}\n{extra}---\nBody.\n"

    def _vault(self, files, index=None):
        d = tempfile.mkdtemp()
        for name, body in files.items():
            with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                f.write(body)
        if index is not None:
            with open(os.path.join(d, "MEMORY.md"), "w", encoding="utf-8") as f:
                f.write(index)
        return d

    def _note(self, name, cluster=None, hook=None, nested=False, desc="d"):
        extra = ""
        if nested:
            extra = "metadata:\n  type: reference\n"
            if cluster:
                extra += "  cluster: %s\n" % cluster
            if hook:
                extra += "  hook: %s\n" % hook
        else:
            if cluster:
                extra += "cluster: %s\n" % cluster
            if hook:
                extra += "hook: %s\n" % hook
        return self.NOTE.format(name=name, desc=desc, extra=extra)

    def _run(self, d, *argv):
        buf_out, buf_err = io.StringIO(), io.StringIO()
        old = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = buf_out, buf_err
        try:
            rc = indexer.run(list(argv), mem_dir=d)
        finally:
            sys.stdout, sys.stderr = old
        return rc, buf_out.getvalue(), buf_err.getvalue()

    def _index(self, d):
        return pathlib.Path(d, "MEMORY.md").read_text()

    MARKERS = "# Memory\n\n" + indexer.BEGIN + "\n" + indexer.END + "\n"

    def test_every_memory_gets_a_pointer(self):
        d = self._vault({
            "reference_a.md": self._note("reference_a", cluster="Alpha", hook="first"),
            "reference_b.md": self._note("reference_b", cluster="Beta"),
        }, self.MARKERS)
        rc, out, err = self._run(d, "build")
        self.assertEqual(rc, 0, err)
        idx = self._index(d)
        self.assertIn("`reference_a.md` first", idx)
        self.assertIn("`reference_b.md`", idx)
        self.assertIn("**Alpha.**", idx)
        self.assertIn("**Beta.**", idx)

    def test_resident_memory_is_not_duplicated_in_generated_block(self):
        index = ("# Memory\n\n## Hard rules\n- rule (`feedback_x.md`)\n\n"
                 + indexer.BEGIN + "\n" + indexer.END + "\n")
        d = self._vault({
            "feedback_x.md": self._note("feedback_x", cluster="Voice"),
            "reference_y.md": self._note("reference_y", cluster="Voice"),
        }, index)
        self._run(d, "build")
        idx = self._index(d)
        self.assertEqual(idx.count("feedback_x.md"), 1)   # only the resident mention
        self.assertIn("`reference_y.md`", idx)

    def test_pointer_in_tail_also_counts_as_resident(self):
        index = ("# Memory\n\n" + indexer.BEGIN + "\n" + indexer.END
                 + "\n\n## Learnings\n- see `reference_tail.md`\n")
        d = self._vault({"reference_tail.md": self._note("reference_tail", cluster="X")}, index)
        self._run(d, "build")
        self.assertEqual(self._index(d).count("reference_tail.md"), 1)

    def test_cluster_order_env_then_alpha_then_unsorted_last(self):
        d = self._vault({
            "reference_a.md": self._note("reference_a", cluster="Zeta"),
            "reference_b.md": self._note("reference_b", cluster="Alpha"),
            "reference_c.md": self._note("reference_c", cluster="Mid"),
            "reference_d.md": self._note("reference_d"),                  # no cluster -> Unsorted
        }, self.MARKERS)
        old = os.environ.get("AGENT_MEMORY_CLUSTER_ORDER")
        os.environ["AGENT_MEMORY_CLUSTER_ORDER"] = "Zeta"
        try:
            self._run(d, "build")
        finally:
            if old is None:
                os.environ.pop("AGENT_MEMORY_CLUSTER_ORDER", None)
            else:
                os.environ["AGENT_MEMORY_CLUSTER_ORDER"] = old
        idx = self._index(d)
        order = [idx.index("**%s.**" % c) for c in ("Zeta", "Alpha", "Mid", "Unsorted")]
        self.assertEqual(order, sorted(order))

    def test_nested_metadata_cluster_is_read(self):
        d = self._vault({"reference_n.md": self._note("reference_n", cluster="Nested", hook="h", nested=True)},
                        self.MARKERS)
        self._run(d, "build")
        idx = self._index(d)
        self.assertIn("**Nested.**", idx)
        self.assertIn("`reference_n.md` h", idx)
        self.assertNotIn("Unsorted", idx)

    def test_unsorted_is_a_warning_not_a_problem(self):
        d = self._vault({"reference_u.md": self._note("reference_u")}, self.MARKERS)
        rc, out, err = self._run(d, "build")
        self.assertEqual(rc, 0)
        self.assertIn("Unsorted", out)

    def test_check_is_stale_after_a_new_memory_and_clean_after_build(self):
        d = self._vault({"reference_a.md": self._note("reference_a", cluster="A")}, self.MARKERS)
        self._run(d, "build")
        self.assertEqual(self._run(d, "--check")[0], 0)
        with open(os.path.join(d, "reference_b.md"), "w") as f:
            f.write(self._note("reference_b", cluster="A"))
        rc, out, err = self._run(d, "--check")
        self.assertEqual(rc, 1)
        self.assertIn("STALE", err)
        self._run(d, "build")
        self.assertEqual(self._run(d, "--check")[0], 0)

    def test_check_does_not_write(self):
        d = self._vault({"reference_a.md": self._note("reference_a", cluster="A")}, self.MARKERS)
        before = self._index(d)
        self._run(d, "--check")
        self.assertEqual(self._index(d), before)

    def test_dry_build_does_not_write(self):
        d = self._vault({"reference_a.md": self._note("reference_a", cluster="A")}, self.MARKERS)
        rc, out, _ = self._run(d, "build", "--dry")
        self.assertEqual(rc, 0)
        self.assertIn("would CHANGE", out)
        self.assertEqual(self._index(d), self.MARKERS)

    def test_missing_markers_fails_loudly_and_init_appends_them(self):
        d = self._vault({"reference_a.md": self._note("reference_a", cluster="A")}, "# Memory\n\n## Rules\n")
        rc, out, err = self._run(d, "--check")
        self.assertEqual(rc, 1)
        self.assertIn("markers not found", err)
        rc, out, err = self._run(d, "build", "--init")
        self.assertEqual(rc, 0, err)
        idx = self._index(d)
        self.assertTrue(idx.startswith("# Memory\n\n## Rules\n"))   # existing content kept
        self.assertIn(indexer.BEGIN, idx)
        self.assertIn("`reference_a.md`", idx)

    def test_missing_index_with_init_creates_it(self):
        d = self._vault({"reference_a.md": self._note("reference_a", cluster="A")})
        rc, out, err = self._run(d, "build", "--init")
        self.assertEqual(rc, 0, err)
        self.assertIn("`reference_a.md`", self._index(d))

    def test_over_line_limit_is_a_problem(self):
        d = self._vault({"reference_a.md": self._note("reference_a", cluster="A")},
                        "# Memory\n" + "\n" * 30 + indexer.BEGIN + "\n" + indexer.END + "\n")
        old = os.environ.get("AGENT_MEMORY_LINE_LIMIT")
        os.environ["AGENT_MEMORY_LINE_LIMIT"] = "10"
        try:
            rc, out, err = self._run(d, "build")
        finally:
            if old is None:
                os.environ.pop("AGENT_MEMORY_LINE_LIMIT", None)
            else:
                os.environ["AGENT_MEMORY_LINE_LIMIT"] = old
        self.assertEqual(rc, 1)
        self.assertIn("OVER THE READ LIMIT", err)

    def test_resident_tagged_memory_missing_from_block_is_a_problem(self):
        d = self._vault({"feedback_r.md": self._note("feedback_r", cluster="resident:rules")}, self.MARKERS)
        rc, out, err = self._run(d, "build")
        self.assertEqual(rc, 1)
        self.assertIn("NOT IN RESIDENT BLOCK", self._index(d))
        self.assertIn("resident:*", err)

    def test_unquote_strips_only_matched_pairs(self):
        self.assertEqual(indexer.unquote('"a, b"'), "a, b")
        self.assertEqual(indexer.unquote("'a'"), "a")
        self.assertEqual(indexer.unquote('lead, "the problem"'), 'lead, "the problem"')
        self.assertEqual(indexer.unquote('"unbalanced'), '"unbalanced')

    def test_generated_block_satisfies_the_auditor_coverage_check(self):
        d = self._vault({
            "reference_a.md": self._note("reference_a", cluster="A"),
            "reference_b.md": self._note("reference_b", cluster="B"),
        }, self.MARKERS)
        self._run(d, "build")
        reindex.MEM_DIR = d
        reindex.INDEX = os.path.join(d, "MEMORY.md")
        r = reindex.audit()
        self.assertEqual(r["orphan_files"], [])        # coverage by construction
        self.assertEqual(r["oversize_lines"], [])      # dense cluster lines are not "- " entries

    def test_report_runs(self):
        d = self._vault({"reference_a.md": self._note("reference_a", cluster="A")}, self.MARKERS)
        self._run(d, "build")
        rc, out, err = self._run(d, "--report")
        self.assertEqual(rc, 0, err)
        self.assertIn("COMPOSITION", out)
        self.assertIn("COLDEST", out)


class TestRebuildHook(unittest.TestCase):
    """hooks/memory-index-rebuild.sh: PostToolUse glue that runs the generator."""

    HOOK = ROOT / "hooks" / "memory-index-rebuild.sh"

    def setUp(self):
        import shutil
        if shutil.which("jq") is None:
            self.skipTest("jq not installed")
        self.vault = tempfile.mkdtemp()
        with open(os.path.join(self.vault, "MEMORY.md"), "w") as f:
            f.write("# Memory\n\n" + indexer.BEGIN + "\n" + indexer.END + "\n")
        self.note = os.path.join(self.vault, "reference_x.md")
        with open(self.note, "w") as f:
            f.write("---\nname: reference_x\ndescription: d\ncluster: X\n---\nBody.\n")

    def _run(self, payload, env_vault):
        import json, subprocess
        env = dict(os.environ)
        env.pop("AGENT_MEMORY_DIR", None)
        if env_vault is not None:
            env["AGENT_MEMORY_DIR"] = env_vault
        p = subprocess.run(["bash", str(self.HOOK)], input=json.dumps(payload), capture_output=True,
                           text=True, env=env)
        return p.returncode, p.stdout

    def test_write_inside_vault_rebuilds_index(self):
        rc, out = self._run({"tool_input": {"file_path": self.note}}, self.vault)
        self.assertEqual(rc, 0)
        self.assertIn("`reference_x.md`", pathlib.Path(self.vault, "MEMORY.md").read_text())

    def test_write_outside_vault_is_ignored(self):
        other = os.path.join(tempfile.mkdtemp(), "reference_y.md")
        with open(other, "w") as f:
            f.write("---\nname: reference_y\ndescription: d\n---\n")
        rc, out = self._run({"tool_input": {"file_path": other}}, self.vault)
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")
        self.assertNotIn("reference_x.md", pathlib.Path(self.vault, "MEMORY.md").read_text())

    def test_no_env_is_noop(self):
        rc, out = self._run({"tool_input": {"file_path": self.note}}, None)
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_index_edit_reports_staleness_but_does_not_rebuild(self):
        idx = os.path.join(self.vault, "MEMORY.md")
        rc, out = self._run({"tool_input": {"file_path": idx}}, self.vault)
        self.assertEqual(rc, 0)
        self.assertIn("STALE", out)
        self.assertNotIn("reference_x.md", pathlib.Path(idx).read_text())

    def test_malformed_json_is_noop(self):
        import subprocess
        env = dict(os.environ, AGENT_MEMORY_DIR=self.vault)
        p = subprocess.run(["bash", str(self.HOOK)], input="not json{", capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout, "")


if __name__ == "__main__":
    unittest.main()
