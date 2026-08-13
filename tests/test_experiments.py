import json
from pathlib import Path
import tempfile
import unittest


class ExperimentPolicyTest(unittest.TestCase):
    def test_unknown_and_paid_actions_require_owner(self):
        from money_agent.experiments import classify_action

        self.assertEqual(classify_action("unknown", 0), "OWNER_REQUIRED")
        self.assertEqual(classify_action("write_brief", 1), "OWNER_REQUIRED")

    def test_safe_classes_are_explicit(self):
        from money_agent.experiments import classify_action

        self.assertEqual(classify_action("write_brief", 0), "AUTO_LOCAL")
        self.assertEqual(
            classify_action("prepare_verified_revenue_lane", 0), "AUTO_LOCAL"
        )
        self.assertEqual(
            classify_action("build_owned_asset", 0),
            "CODEX_REVIEWED",
        )
        self.assertEqual(classify_action("send_outreach", 0), "OWNER_REQUIRED")
        self.assertEqual(classify_action("fake_review", 0), "REJECTED")

    def test_export_stays_inside_root_and_redacts_secrets(self):
        from money_agent.experiments import export_work_package

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = {
                "id": 7,
                "project": "FunnelSleuth",
                "deliverable": "Build one owned landing page.",
                "hypothesis": "A focused page attracts qualified visitors.",
                "metric": "qualified_snapshot_runs",
                "autonomy_class": "CODEX_REVIEWED",
                "api_key": "must-not-leak",
                "nested": {"Authorization": "Bearer secret", "safe": "keep"},
            }

            paths = export_work_package(payload, root)

            data = json.loads(paths.json_path.read_text(encoding="utf-8"))
            markdown = paths.markdown_path.read_text(encoding="utf-8")
            self.assertNotIn("api_key", data)
            self.assertNotIn("Authorization", data["nested"])
            self.assertEqual(data["nested"]["safe"], "keep")
            self.assertNotIn("must-not-leak", markdown)
            self.assertTrue(paths.json_path.resolve().is_relative_to(root.resolve()))
            self.assertTrue(
                paths.markdown_path.resolve().is_relative_to(root.resolve())
            )
            self.assertFalse((root / ".next-work.json.tmp").exists())
            self.assertFalse((root / ".HANDOFF.md.tmp").exists())


if __name__ == "__main__":
    unittest.main()
