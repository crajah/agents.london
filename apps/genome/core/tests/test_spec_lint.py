"""Cross-document citation lint runs with the suite: new ambiguity fails."""
import pathlib
import subprocess
import sys
import unittest


class TestSpecLint(unittest.TestCase):
    def test_no_unqualified_ambiguous_citations(self):
        script = (pathlib.Path(__file__).resolve().parents[2]
                  / "validation" / "spec_lint.py")
        res = subprocess.run([sys.executable, str(script)],
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)


if __name__ == "__main__":
    unittest.main()
