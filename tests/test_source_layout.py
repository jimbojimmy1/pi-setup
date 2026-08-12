from pathlib import Path
import py_compile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SourceLayoutTest(unittest.TestCase):
    def test_runtime_modules_are_versioned_and_compile(self):
        for name in ("store.py", "llm.py", "agent.py", "app.py"):
            path = ROOT / "money_agent" / name
            self.assertTrue(path.is_file(), name)
            py_compile.compile(str(path), doraise=True)

    def test_ci_runs_python_and_installer_suites(self):
        workflow = ROOT / ".github" / "workflows" / "ci.yml"
        self.assertTrue(workflow.is_file())
        text = workflow.read_text(encoding="utf-8")
        self.assertIn("python3 -m unittest discover -s tests -v", text)
        self.assertIn("bash -n setup-money-agent.sh", text)
        self.assertIn("bash tests/test_installer.sh", text)
        self.assertIn("uses: actions/checkout@v5", text)
        self.assertIn("uses: actions/setup-python@v6", text)


if __name__ == "__main__":
    unittest.main()
