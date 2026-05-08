import contextlib
import io
import json
from pathlib import Path
import unittest

from astrid.packs.builtin.inspect_cut import run as inspect_cut

from tests.helpers.fixture_case import make_brief_case


class InspectCutTest(unittest.TestCase):
    def test_invocation_smoke_renders_script_and_structure(self) -> None:
        case = make_brief_case(self)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(inspect_cut.main([str(case["run_dir"]), "--no-color"]), 0)
        output = stdout.getvalue()
        self.assertIn("SCRIPT", output)
        self.assertIn("STRUCTURE", output)
        self.assertIn("[visual stinger] OPEN", output)
        self.assertIn("mid_sentence_end", output)
        self.assertIn("▒", output)

    def test_clip_zoom_rendering(self) -> None:
        case = make_brief_case(self)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(inspect_cut.main([str(case["run_dir"]), "--clip", "2", "--no-color"]), 0)
        output = stdout.getvalue()
        self.assertIn("CLIP 2", output)
        self.assertIn("fix_options", output)
        self.assertIn("before_transcript=First clean quote", output)
        self.assertIn("after_transcript=First clean quote.", output)

    def test_json_output_parseability(self) -> None:
        case = make_brief_case(self)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(inspect_cut.main([str(case["run_dir"]), "--clip", "2", "--json"]), 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(Path(payload["run_dir"]).resolve(), Path(case["run_dir"]).resolve())
        self.assertIn("script", payload)
        self.assertIn("structure", payload)
        self.assertEqual(payload["clip"]["order"], 2)


if __name__ == "__main__":
    unittest.main()
