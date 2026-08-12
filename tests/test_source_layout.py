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


if __name__ == "__main__":
    unittest.main()
