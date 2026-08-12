import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class AgentExperimentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        os.environ["MA_DB"] = str(self.root / "money.db")
        os.environ["MA_ARTIFACT_ROOT"] = str(self.root / "artifacts")
        os.environ["MA_TRUSTED_MEASUREMENT_SOURCES"] = "analytics_readonly"

        import money_agent.store as store

        self.store = importlib.reload(store)
        self.store.init()

    def tearDown(self):
        self.store.close_connection()
        os.environ.pop("MA_DB", None)
        os.environ.pop("MA_ARTIFACT_ROOT", None)
        os.environ.pop("MA_TRUSTED_MEASUREMENT_SOURCES", None)
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
                "measurement_source": "analytics_readonly",
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
        self.assertEqual(
            experiments[0]["measurement_source"], "analytics_readonly"
        )

        exported = agent.export_next_experiment()

        self.assertEqual(exported["id"], first)
        payload = json.loads(
            (self.root / "artifacts" / "next-work.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["project"], "FunnelSleuth")
        self.assertEqual(payload["autonomy_class"], "CODEX_REVIEWED")
        self.assertEqual(payload["measurement_source"], "analytics_readonly")
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

    def test_model_cannot_self_authorize_a_measurement_source(self):
        import money_agent.agent as agent_module

        agent_module = importlib.reload(agent_module)
        agent = agent_module.Agent.__new__(agent_module.Agent)
        idea_id = self.store.add_idea("Unconfigured analytics")
        os.environ.pop("MA_TRUSTED_MEASUREMENT_SOURCES", None)

        experiment_id = agent.persist_experiment(idea_id, self.promoted_judge())

        experiment = self.store.get_experiment(experiment_id)
        self.assertEqual(experiment["measurement_source"], "")

    def test_monitoring_blocks_unmeasurable_work_before_more_research(self):
        import money_agent.agent as agent_module

        agent_module = importlib.reload(agent_module)
        agent = agent_module.Agent.__new__(agent_module.Agent)
        idea_id = self.store.add_idea("No source")
        judge = self.promoted_judge()
        judge["experiment"]["measurement_source"] = ""
        experiment_id = agent.persist_experiment(idea_id, judge)

        monitored = agent.monitor_experiments()

        self.assertEqual(monitored, 1)
        self.assertEqual(
            self.store.get_experiment(experiment_id)["status"], "blocked"
        )

    def test_tick_processes_inbox_then_monitoring_before_export(self):
        import money_agent.agent as agent_module

        agent_module = importlib.reload(agent_module)
        agent = agent_module.Agent.__new__(agent_module.Agent)
        calls = []

        agent.over_budget = lambda: False
        agent.process_observation_inbox = lambda: calls.append("inbox")
        agent.monitor_experiments = lambda: calls.append("monitor")
        agent.export_next_experiment = lambda: calls.append("export") or {"id": 1}
        agent.unit = lambda: calls.append("research")

        agent.tick()

        self.assertEqual(calls, ["inbox", "monitor", "export"])

    def test_monitoring_collects_public_health_for_health_sources(self):
        import money_agent.agent as agent_module

        agent_module = importlib.reload(agent_module)
        agent = agent_module.Agent.__new__(agent_module.Agent)
        idea_id = self.store.add_idea("FunnelSleuth health")
        experiment_id = self.store.add_experiment(
            idea_id=idea_id,
            project="FunnelSleuth",
            action_kind="public_health_check",
            hypothesis="The public page remains reachable.",
            deliverable="Check the public page.",
            metric="public_availability",
            stop_condition="Escalate repeated failures.",
            window_days=30,
            autonomy_class="AUTO_LOCAL",
            hours=0,
            cost_usd=0,
            measurement_source="public_http:https://example.com/health",
        )

        with patch.object(agent_module, "monitor_experiment") as validate:
            with patch.object(agent_module, "collect_public_health") as collect:
                monitored = agent.monitor_experiments()

        self.assertEqual(monitored, 1)
        validate.assert_called_once_with(experiment_id)
        collect.assert_called_once_with(experiment_id)

    def test_inbox_uses_configured_artifact_root_and_bound(self):
        import money_agent.agent as agent_module

        agent_module = importlib.reload(agent_module)
        agent = agent_module.Agent.__new__(agent_module.Agent)
        expected = self.root / "artifacts"

        with patch.object(agent_module, "process_inbox") as process:
            process.return_value = {"accepted": 0, "rejected": 0, "remaining": 0}
            result = agent.process_observation_inbox()

        self.assertEqual(result["accepted"], 0)
        process.assert_called_once_with(str(expected), limit=25)

    def test_inbox_failure_is_recorded_without_killing_tick_or_leaking_detail(self):
        import money_agent.agent as agent_module

        agent_module = importlib.reload(agent_module)
        agent = agent_module.Agent.__new__(agent_module.Agent)

        with patch.object(
            agent_module, "process_inbox", side_effect=OSError("secret-file-name")
        ), patch.object(agent_module, "log"):
            result = agent.process_observation_inbox()

        self.assertTrue(result["error"])
        recorded = self.store.get_meta("inbox_error", "")
        self.assertIn("OSError", recorded)
        self.assertNotIn("secret-file-name", recorded)


if __name__ == "__main__":
    unittest.main()
