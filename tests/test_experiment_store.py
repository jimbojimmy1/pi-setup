import importlib
import os
from pathlib import Path
import tempfile
import unittest


class ExperimentStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["MA_DB"] = str(Path(self.tmp.name) / "money.db")
        import money_agent.store as store

        self.store = importlib.reload(store)
        self.store.init()

    def tearDown(self):
        connection = getattr(self.store._local, "c", None)
        if connection is not None:
            connection.close()
            self.store._local.c = None
        os.environ.pop("MA_DB", None)
        self.tmp.cleanup()

    def add_ready_experiment(self, title="FunnelSleuth organic landing page"):
        idea_id = self.store.add_idea(title)
        experiment_id = self.store.add_experiment(
            idea_id=idea_id,
            project="FunnelSleuth",
            action_kind="build_owned_asset",
            hypothesis="A niche audit page attracts qualified visitors.",
            deliverable="Create one audit page for local roofers.",
            metric="qualified_snapshot_runs",
            stop_condition="Stop after 30 days with no qualified runs.",
            window_days=30,
            autonomy_class="CODEX_REVIEWED",
            hours=2,
            cost_usd=0,
        )
        return idea_id, experiment_id

    def test_add_and_claim_ready_experiment(self):
        _, experiment_id = self.add_ready_experiment()

        claimed = self.store.claim_experiment(lease_seconds=300)

        self.assertEqual(claimed["id"], experiment_id)
        self.assertEqual(claimed["status"], "exported")
        self.assertGreater(claimed["lease_until"], claimed["updated_at"])

    def test_stale_export_is_recovered(self):
        _, experiment_id = self.add_ready_experiment("Recover me")
        self.store.claim_experiment(lease_seconds=-1)

        recovered = self.store.recover_stale_experiments()

        self.assertEqual(recovered, 1)
        self.assertEqual(
            self.store.get_experiment(experiment_id)["status"],
            "ready",
        )

    def test_schema_migration_preserves_existing_ideas(self):
        idea_id = self.store.add_idea("Existing idea")

        self.store.init()

        self.assertEqual(self.store.get_idea(idea_id)["title"], "Existing idea")
        self.assertEqual(self.store.list_experiments(), [])

    def test_experiment_events_are_append_only(self):
        _, experiment_id = self.add_ready_experiment("Eventful experiment")

        first = self.store.add_experiment_event(
            experiment_id,
            "ready",
            "Experiment passed validation.",
        )
        second = self.store.add_experiment_event(
            experiment_id,
            "observation",
            "No measurement source configured.",
        )

        events = self.store.experiment_events(experiment_id)
        self.assertEqual([event["id"] for event in events], [first, second])
        self.assertEqual(events[1]["event_type"], "observation")


if __name__ == "__main__":
    unittest.main()
