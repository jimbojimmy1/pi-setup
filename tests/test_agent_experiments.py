import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest


class AgentExperimentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        os.environ["MA_DB"] = str(self.root / "money.db")
        os.environ["MA_ARTIFACT_ROOT"] = str(self.root / "artifacts")

        import money_agent.store as store

        self.store = importlib.reload(store)
        self.store.init()

    def tearDown(self):
        self.store.close_connection()
        os.environ.pop("MA_DB", None)
        os.environ.pop("MA_ARTIFACT_ROOT", None)
        self.tmp.cleanup()

    def promoted_judge(self):
        return {
            "verdict": "PROMOTE",
            "score": 82,
            "experiment": {
                "project": "FunnelSleuth",
                "action_kind": "build_owned_asset",
                "hypothesis": (
                    "A roofer-specific page produces qualified snapshot runs."
                ),
                "deliverable": "Create one evidence-led roofer audit page.",
                "metric": "qualified_snapshot_runs from FunnelSleuth analytics",
                "window_days": 30,
                "hours": 2,
                "cost_usd": 0,
                "stop_condition": (
                    "Stop after 30 days with zero qualified snapshot runs."
                ),
                "autonomy_class": "AUTO_LOCAL",
            },
        }

    def test_promoted_result_creates_one_policy_classified_work_package(self):
        import money_agent.agent as agent_module

        agent_module = importlib.reload(agent_module)
        agent = agent_module.Agent.__new__(agent_module.Agent)
        idea_id = self.store.add_idea("FunnelSleuth roofer page")
        judge = self.promoted_judge()

        first = agent.persist_experiment(idea_id, judge)
        second = agent.persist_experiment(idea_id, judge)

        self.assertEqual(first, second)
        experiments = self.store.list_experiments()
        self.assertEqual(len(experiments), 1)
        self.assertEqual(experiments[0]["autonomy_class"], "CODEX_REVIEWED")

        exported = agent.export_next_experiment()

        self.assertEqual(exported["id"], first)
        payload = json.loads(
            (self.root / "artifacts" / "next-work.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["project"], "FunnelSleuth")
        self.assertEqual(payload["autonomy_class"], "CODEX_REVIEWED")
        self.assertIn("stop_condition", payload)

    def test_non_promoted_or_invalid_experiment_is_not_persisted(self):
        import money_agent.agent as agent_module

        agent_module = importlib.reload(agent_module)
        agent = agent_module.Agent.__new__(agent_module.Agent)
        idea_id = self.store.add_idea("Not ready")

        judge = self.promoted_judge()
        judge["verdict"] = "ITERATE"
        self.assertIsNone(agent.persist_experiment(idea_id, judge))

        judge["verdict"] = "PROMOTE"
        judge["experiment"]["metric"] = ""
        self.assertIsNone(agent.persist_experiment(idea_id, judge))
        self.assertEqual(self.store.list_experiments(), [])


if __name__ == "__main__":
    unittest.main()
