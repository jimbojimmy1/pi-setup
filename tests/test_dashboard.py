import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest


class DashboardStateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        os.environ["MA_DB"] = str(self.root / "money.db")
        os.environ["MA_ARTIFACT_ROOT"] = str(self.root / "artifacts")
        os.environ["ANTHROPIC_API_KEY"] = "must-not-appear"

        import money_agent.store as store

        self.store = importlib.reload(store)
        self.store.init()
        idea_id = self.store.add_idea("FunnelSleuth experiment")
        self.store.add_experiment(
            idea_id=idea_id,
            project="FunnelSleuth",
            action_kind="build_owned_asset",
            hypothesis="A specific page produces qualified runs.",
            deliverable="Build a roofer audit page.",
            metric="qualified runs in FunnelSleuth analytics",
            stop_condition="Stop after 30 days with no qualified runs.",
            window_days=30,
            autonomy_class="CODEX_REVIEWED",
            hours=2,
            cost_usd=0,
            measurement_source="analytics_readonly",
        )
        experiment_id = self.store.list_experiments()[0]["id"]
        self.store.add_observation(
            experiment_id=experiment_id,
            source_kind="analytics_readonly",
            metric="qualified runs in FunnelSleuth analytics",
            value=2,
            revenue_usd=0,
            evidence_ref="analytics:2",
            observed_at=1000,
        )
        artifacts = self.root / "artifacts"
        artifacts.mkdir()
        (artifacts / "next-work.json").write_text(
            json.dumps({"project": "FunnelSleuth", "next_action": "Build page"}),
            encoding="utf-8",
        )

    def tearDown(self):
        self.store.close_connection()
        os.environ.pop("MA_DB", None)
        os.environ.pop("MA_ARTIFACT_ROOT", None)
        os.environ.pop("ANTHROPIC_API_KEY", None)
        self.tmp.cleanup()

    def test_state_exposes_work_and_owner_blockers_without_secrets(self):
        import money_agent.app as app_module

        app_module = importlib.reload(app_module)
        response = app_module.app.test_client().get("/api/state")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["experiments"][0]["project"], "FunnelSleuth")
        self.assertEqual(payload["next_work"]["next_action"], "Build page")
        self.assertTrue(payload["owner_blockers"])
        self.assertEqual(payload["observations"][0]["source_kind"], "analytics_readonly")
        self.assertNotIn("evidence_ref", payload["observations"][0])
        self.assertNotIn("must-not-appear", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
