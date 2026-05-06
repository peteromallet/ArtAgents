"""Tests for the multi-harness skills install layer."""

from __future__ import annotations

import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import yaml

from artagents import skills
from artagents.skills import discovery, state
from artagents.skills.harnesses import (
    ClaudeAdapter,
    CodexAdapter,
    HermesAdapter,
)
from artagents.skills.harnesses.codex import BEGIN_MARKER, END_MARKER


class _Tmp:
    """Test fixture that pins a tmpdir as $HOME and as the state home."""

    def __init__(self) -> None:
        self._td = TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.home = self.tmp / "home"
        self.home.mkdir()
        (self.home / ".claude").mkdir()
        (self.home / ".codex").mkdir()
        (self.home / ".hermes").mkdir()
        self.state_path = self.tmp / "state.json"
        self._patches = [
            mock.patch.dict("os.environ", {
                "HOME": str(self.home),
                "ARTAGENTS_STATE_HOME": str(self.tmp / "_state"),
                "ARTAGENTS_NO_NUDGE": "",
            }, clear=False),
            mock.patch.object(Path, "home", return_value=self.home),
        ]
        for patch in self._patches:
            patch.start()

    def close(self) -> None:
        for patch in reversed(self._patches):
            patch.stop()
        self._td.cleanup()


def _descriptors():
    return discovery.list_skills()


class AdapterPlanTest(unittest.TestCase):
    def test_claude_target_for_core_uses_artagents_path(self) -> None:
        fx = _Tmp()
        try:
            adapter = ClaudeAdapter()
            descriptor = next(d for d in _descriptors() if d.pack_id == "_core")
            self.assertEqual(adapter.target_for(descriptor), fx.home / ".claude" / "skills" / "artagents")
        finally:
            fx.close()

    def test_codex_target_for_core_uses_artagents_path(self) -> None:
        fx = _Tmp()
        try:
            adapter = CodexAdapter()
            descriptor = next(d for d in _descriptors() if d.pack_id == "_core")
            self.assertEqual(adapter.target_for(descriptor), fx.home / ".codex" / "skills" / "artagents")
        finally:
            fx.close()

    def test_hermes_target_for_core_uses_artagents_path(self) -> None:
        fx = _Tmp()
        try:
            adapter = HermesAdapter()
            descriptor = next(d for d in _descriptors() if d.pack_id == "_core")
            self.assertEqual(adapter.target_for(descriptor), fx.home / ".hermes" / "skills" / "artagents")
        finally:
            fx.close()


class ApplyTest(unittest.TestCase):
    def test_apply_creates_symlink_and_is_idempotent(self) -> None:
        fx = _Tmp()
        try:
            adapter = ClaudeAdapter()
            descriptors = _descriptors()
            adapter.apply("install", descriptors)
            target = adapter.target_for(descriptors[0])
            self.assertTrue(target.is_symlink())
            steps = adapter.apply("install", descriptors)
            # Second apply must be a no-op.
            self.assertTrue(all(not step.extras.get("changed") for step in steps))
        finally:
            fx.close()

    def test_codex_agents_md_block_added_then_byte_stable(self) -> None:
        fx = _Tmp()
        try:
            adapter = CodexAdapter()
            descriptors = _descriptors()
            adapter.apply("install", descriptors, all_after_descriptors=descriptors)
            agents_md = fx.home / ".codex" / "AGENTS.md"
            self.assertTrue(agents_md.exists())
            text1 = agents_md.read_text(encoding="utf-8")
            self.assertIn(BEGIN_MARKER, text1)
            self.assertIn(END_MARKER, text1)
            adapter.apply("install", descriptors, all_after_descriptors=descriptors)
            text2 = agents_md.read_text(encoding="utf-8")
            self.assertEqual(text1, text2)
        finally:
            fx.close()

    def test_codex_agents_md_block_removed_on_uninstall(self) -> None:
        fx = _Tmp()
        try:
            adapter = CodexAdapter()
            descriptors = _descriptors()
            adapter.apply("install", descriptors, all_after_descriptors=descriptors)
            adapter.apply("uninstall", descriptors, all_after_descriptors=[])
            text = (fx.home / ".codex" / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn(BEGIN_MARKER, text)
            self.assertIn("_no ArtAgents skills installed_", text)
        finally:
            fx.close()

    def test_codex_block_preserves_surrounding_user_content(self) -> None:
        fx = _Tmp()
        try:
            agents_md = fx.home / ".codex" / "AGENTS.md"
            agents_md.write_text("# my notes\n\npreface line\n", encoding="utf-8")
            adapter = CodexAdapter()
            descriptors = _descriptors()
            adapter.apply("install", descriptors, all_after_descriptors=descriptors)
            text = agents_md.read_text(encoding="utf-8")
            self.assertIn("# my notes", text)
            self.assertIn("preface line", text)
            self.assertIn(BEGIN_MARKER, text)
        finally:
            fx.close()


class HermesExternalDirTest(unittest.TestCase):
    def test_external_dir_install_adds_entry_and_preserves_other_keys(self) -> None:
        fx = _Tmp()
        try:
            cfg_path = fx.home / ".hermes" / "config.yaml"
            cfg_path.write_text(yaml.safe_dump({"other": {"keep": True}, "skills": {"external_dirs": ["/already/here"]}}), encoding="utf-8")
            adapter = HermesAdapter()
            descriptors = _descriptors()
            adapter.apply("install", descriptors, mechanism="external-dir")
            data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
            self.assertEqual(data["other"], {"keep": True})
            self.assertIn("/already/here", data["skills"]["external_dirs"])
            self.assertEqual(len([entry for entry in data["skills"]["external_dirs"] if entry.endswith("/artagents/packs")]), 1)
        finally:
            fx.close()

    def test_external_dir_uninstall_removes_entry(self) -> None:
        fx = _Tmp()
        try:
            adapter = HermesAdapter()
            descriptors = _descriptors()
            adapter.apply("install", descriptors, mechanism="external-dir")
            adapter.apply("uninstall", descriptors, mechanism="external-dir")
            data = yaml.safe_load((fx.home / ".hermes" / "config.yaml").read_text(encoding="utf-8"))
            external_dirs = (data.get("skills") or {}).get("external_dirs") or []
            self.assertFalse(any(entry.endswith("/artagents/packs") for entry in external_dirs))
        finally:
            fx.close()


class DoctorTest(unittest.TestCase):
    def test_doctor_reports_drift_when_target_renamed(self) -> None:
        fx = _Tmp()
        try:
            skills.install(pack_ids=["_core"], harness_names=["claude"])
            adapter = ClaudeAdapter()
            descriptor = next(d for d in _descriptors() if d.pack_id == "_core")
            target = adapter.target_for(descriptor)
            target.unlink()
            target.symlink_to(fx.tmp / "does-not-exist")
            report = skills.doctor()
            failures = [r for r in report["results"] if not r["ok"] and r["pack"] == "_core"]
            self.assertTrue(failures, msg=str(report))
        finally:
            fx.close()


class DriftAndHealTest(unittest.TestCase):
    """list/doctor must cross-check the filesystem and self-heal on demand."""

    def _install_then_wipe_state(self, harness: str, *, mechanism: str = "symlink") -> _Tmp:
        fx = _Tmp()
        kwargs: dict = {}
        if harness == "hermes":
            kwargs["mechanism"] = mechanism
        skills.install(pack_ids=["_core"], harness_names=[harness], **kwargs)
        # Wipe the state file but leave the filesystem install intact.
        sp = state.state_path()
        if sp.exists():
            sp.unlink()
        return fx

    def test_list_with_state_missing_but_symlinks_present_reports_drift_claude(self) -> None:
        fx = self._install_then_wipe_state("claude")
        try:
            report = skills.list_state()
            core = next(p for p in report["packs"] if p["pack_id"] == "_core")
            entry = core["harnesses"]["claude"]
            self.assertTrue(entry["installed"])
            self.assertTrue(entry["fs_installed"])
            self.assertFalse(entry["state_installed"])
            self.assertTrue(entry["drift"])
        finally:
            fx.close()

    def test_list_with_state_missing_but_symlinks_present_reports_drift_codex(self) -> None:
        fx = self._install_then_wipe_state("codex")
        try:
            report = skills.list_state()
            core = next(p for p in report["packs"] if p["pack_id"] == "_core")
            entry = core["harnesses"]["codex"]
            self.assertTrue(entry["fs_installed"])
            self.assertTrue(entry["drift"])
        finally:
            fx.close()

    def test_list_with_state_missing_but_symlinks_present_reports_drift_hermes(self) -> None:
        fx = self._install_then_wipe_state("hermes")
        try:
            report = skills.list_state()
            core = next(p for p in report["packs"] if p["pack_id"] == "_core")
            entry = core["harnesses"]["hermes"]
            self.assertTrue(entry["fs_installed"])
            self.assertTrue(entry["drift"])
        finally:
            fx.close()

    def test_list_with_state_claiming_but_symlink_missing_reports_drift(self) -> None:
        fx = _Tmp()
        try:
            # Manually record an install in the state file with no on-disk evidence.
            data = state.load()
            state.record_install(data, "claude", "_core", target="/tmp/fake", mechanism="symlink")
            state.save(data)
            report = skills.list_state()
            core = next(p for p in report["packs"] if p["pack_id"] == "_core")
            entry = core["harnesses"]["claude"]
            self.assertTrue(entry["state_installed"])
            self.assertFalse(entry["fs_installed"])
            self.assertTrue(entry["drift"])
        finally:
            fx.close()

    def test_doctor_heal_rewrites_state_from_filesystem_reality(self) -> None:
        fx = self._install_then_wipe_state("claude")
        try:
            # Pre-condition: state file gone.
            self.assertFalse(state.state_path().exists())
            report = skills.doctor(heal=True)
            self.assertTrue(any(d["pack"] == "_core" and d["harness"] == "claude" for d in report["drift"]))
            self.assertTrue(any(h["pack"] == "_core" and h["harness"] == "claude" for h in report["healed"]))
            # Post-condition: state file now records the install.
            data = state.load()
            self.assertIn("_core", data["installs"]["claude"])
            # Re-running doctor without heal should now show no drift.
            report2 = skills.doctor()
            self.assertEqual(report2["drift"], [])
        finally:
            fx.close()

    def test_doctor_heal_works_for_codex_and_hermes(self) -> None:
        for harness in ("codex", "hermes"):
            fx = self._install_then_wipe_state(harness)
            try:
                report = skills.doctor(heal=True)
                self.assertTrue(
                    any(h["harness"] == harness for h in report["healed"]),
                    msg=f"{harness}: no healed entries: {report}",
                )
                data = state.load()
                self.assertIn("_core", data["installs"][harness])
            finally:
                fx.close()

    def test_doctor_heal_clears_state_when_filesystem_disagrees(self) -> None:
        fx = _Tmp()
        try:
            data = state.load()
            state.record_install(data, "claude", "_core", target="/tmp/fake", mechanism="symlink")
            state.save(data)
            report = skills.doctor(heal=True)
            self.assertTrue(any(d["kind"] == "fs-missing" for d in report["drift"]))
            self.assertTrue(any(h["action"] == "removed-from-state" for h in report["healed"]))
            data2 = state.load()
            self.assertNotIn("_core", data2["installs"]["claude"])
        finally:
            fx.close()


class StateRoundtripTest(unittest.TestCase):
    def test_state_round_trip(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "skills.json"
            data = state.load(path)
            state.record_install(data, "claude", "_core", target="/x", mechanism="symlink")
            state.record_nudge(data, "codex")
            state.save(data, path)
            reloaded = state.load(path)
            self.assertEqual(reloaded["installs"]["claude"]["_core"]["target"], "/x")
            self.assertIsNotNone(reloaded["nudge"]["codex"]["last_shown_at"])


class NudgeTest(unittest.TestCase):
    def test_nudge_fires_when_stale(self) -> None:
        fx = _Tmp()
        try:
            stream = io.StringIO()
            fired = skills.nudge_if_needed(argv=["doctor"], stream=stream)
            self.assertTrue(fired)
            self.assertIn("[artagents]", stream.getvalue())
        finally:
            fx.close()

    def test_nudge_does_not_fire_inside_skills_subcommand(self) -> None:
        fx = _Tmp()
        try:
            stream = io.StringIO()
            fired = skills.nudge_if_needed(argv=["skills", "list"], stream=stream)
            self.assertFalse(fired)
            self.assertEqual(stream.getvalue(), "")
        finally:
            fx.close()

    def test_nudge_suppressed_by_env(self) -> None:
        fx = _Tmp()
        try:
            with mock.patch.dict("os.environ", {"ARTAGENTS_NO_NUDGE": "1"}):
                stream = io.StringIO()
                fired = skills.nudge_if_needed(argv=["doctor"], stream=stream)
                self.assertFalse(fired)
                self.assertEqual(stream.getvalue(), "")
        finally:
            fx.close()

    def test_nudge_rate_limited_after_recent_show(self) -> None:
        fx = _Tmp()
        try:
            stream = io.StringIO()
            self.assertTrue(skills.nudge_if_needed(argv=["doctor"], stream=stream))
            stream2 = io.StringIO()
            self.assertFalse(skills.nudge_if_needed(argv=["doctor"], stream=stream2))
            self.assertEqual(stream2.getvalue(), "")
        finally:
            fx.close()

    def test_nudge_quiet_flag_suppresses(self) -> None:
        fx = _Tmp()
        try:
            stream = io.StringIO()
            self.assertFalse(skills.nudge_if_needed(argv=["doctor", "--quiet"], stream=stream))
        finally:
            fx.close()


class LintTest(unittest.TestCase):
    def test_lint_flags_hermes_token(self) -> None:
        findings = discovery.lint_shared_skill_md("Hello ${HERMES_HOME}!")
        self.assertTrue(findings)

    def test_lint_flags_shell_backtick_token(self) -> None:
        findings = discovery.lint_shared_skill_md("see !`uname -a` here")
        self.assertTrue(findings)

    def test_lint_passes_clean_text(self) -> None:
        self.assertEqual(discovery.lint_shared_skill_md("nothing forbidden here"), [])


if __name__ == "__main__":
    unittest.main()
