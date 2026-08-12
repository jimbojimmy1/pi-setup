import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest


class ObservationInboxTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        os.environ["MA_DB"] = str(self.root / "money.db")
        import money_agent.store as store

        self.store = importlib.reload(store)
        self.store.init()
        idea_id = self.store.add_idea("Inbox experiment")
        self.experiment_id = self.store.add_experiment(
            idea_id=idea_id,
            project="FunnelSleuth",
            action_kind="build_owned_asset",
            hypothesis="A niche page produces qualified runs.",
            deliverable="Build the niche page.",
            metric="qualified runs",
            stop_condition="Stop after 30 days with no qualified runs.",
            window_days=30,
            autonomy_class="CODEX_REVIEWED",
            hours=2,
            cost_usd=0,
            measurement_source="analytics_readonly",
        )

    def tearDown(self):
        self.store.close_connection()
        os.environ.pop("MA_DB", None)
        self.tmp.cleanup()

    def payload(self, evidence_ref="analytics:inbox-1"):
        return {
            "experiment_id": self.experiment_id,
            "source_kind": "analytics_readonly",
            "metric": "qualified runs",
            "value": 2,
            "evidence_ref": evidence_ref,
            "observed_at": 1000,
        }

    def incoming(self):
        path = self.root / "observation-inbox" / "incoming"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def test_accepts_and_archives_one_observation_inside_root(self):
        from money_agent.inbox import process_inbox

        source = self.incoming() / "event.json"
        source.write_text(json.dumps(self.payload()), encoding="utf-8")

        result = process_inbox(self.root)

        self.assertEqual(result, {"accepted": 1, "rejected": 0, "remaining": 0})
        self.assertFalse(source.exists())
        accepted = list((self.root / "observation-inbox" / "accepted").iterdir())
        self.assertEqual(len(accepted), 1)
        self.assertTrue(accepted[0].resolve().is_relative_to(self.root.resolve()))
        self.assertEqual(len(self.store.list_observations(self.experiment_id)), 1)

    def test_rejects_without_exposing_payload_in_summary(self):
        from money_agent.inbox import process_inbox

        secret = "must-not-leak"
        source = self.incoming() / "bad.json"
        source.write_text(
            json.dumps({**self.payload(), "api_key": secret}), encoding="utf-8"
        )

        result = process_inbox(self.root)

        self.assertEqual(result["rejected"], 1)
        self.assertNotIn(secret, json.dumps(result))
        rejected = list((self.root / "observation-inbox" / "rejected").iterdir())
        self.assertEqual(len(rejected), 1)

    def test_limit_bounds_work_and_duplicate_evidence_remains_idempotent(self):
        from money_agent.inbox import process_inbox

        incoming = self.incoming()
        for index in range(3):
            (incoming / f"{index}.json").write_text(
                json.dumps(self.payload("analytics:same")), encoding="utf-8"
            )

        first = process_inbox(self.root, limit=2)
        second = process_inbox(self.root, limit=2)

        self.assertEqual(first["accepted"], 2)
        self.assertEqual(first["remaining"], 1)
        self.assertEqual(second["accepted"], 1)
        self.assertEqual(len(self.store.list_observations(self.experiment_id)), 1)

    def test_symlink_is_rejected_without_reading_external_target(self):
        from money_agent.inbox import process_inbox

        outside = self.root.parent / f"{self.root.name}-outside.json"
        outside.write_text(json.dumps(self.payload()), encoding="utf-8")
        link = self.incoming() / "link.json"
        try:
            link.symlink_to(outside)
        except OSError:
            outside.unlink(missing_ok=True)
            self.skipTest("symlink creation is unavailable")
        try:
            result = process_inbox(self.root)
            self.assertEqual(result["rejected"], 1)
            self.assertTrue(outside.exists())
            self.assertEqual(self.store.list_observations(self.experiment_id), [])
        finally:
            outside.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
