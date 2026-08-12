import importlib
import os
from pathlib import Path
import socket
import tempfile
import unittest


class MonitoringTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["MA_DB"] = str(Path(self.tmp.name) / "money.db")
        import money_agent.store as store

        self.store = importlib.reload(store)
        self.store.init()

    def tearDown(self):
        self.store.close_connection()
        os.environ.pop("MA_DB", None)
        self.tmp.cleanup()

    def add_experiment(self, measurement_source="analytics_readonly"):
        idea_id = self.store.add_idea("Monitor me")
        return self.store.add_experiment(
            idea_id=idea_id,
            project="FunnelSleuth",
            action_kind="build_owned_asset",
            hypothesis="A niche page produces qualified runs.",
            deliverable="Build a niche page.",
            metric="qualified runs",
            stop_condition="Stop after 30 days with none.",
            window_days=30,
            autonomy_class="CODEX_REVIEWED",
            hours=2,
            cost_usd=0,
            measurement_source=measurement_source,
        )

    def test_public_url_accepts_only_global_https_default_port(self):
        from money_agent.monitoring import MonitoringError, validate_public_https_url

        def global_resolver(host, port, type=0):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

        self.assertEqual(
            validate_public_https_url(
                "https://example.com/health", resolver=global_resolver
            ),
            "https://example.com/health",
        )
        invalid = (
            "http://example.com",
            "https://user@example.com",
            "https://example.com:8443",
            "https://127.0.0.1",
            "https://169.254.1.1",
            "https://10.0.0.1",
            "https://192.0.2.1",
        )
        for url in invalid:
            with self.subTest(url=url), self.assertRaises(MonitoringError):
                validate_public_https_url(url, resolver=global_resolver)

    def test_missing_source_blocks_once(self):
        from money_agent.monitoring import monitor_experiment

        experiment_id = self.add_experiment(measurement_source="")

        first = monitor_experiment(experiment_id)
        second = monitor_experiment(experiment_id)

        self.assertEqual(first["status"], "blocked")
        self.assertEqual(second["status"], "blocked")
        blocked_events = [
            event
            for event in self.store.experiment_events(experiment_id)
            if event["event_type"] == "blocked"
        ]
        self.assertEqual(len(blocked_events), 1)
        self.assertIn("measurement source", blocked_events[0]["detail"])

    def test_matching_evidence_is_idempotent_and_starts_measurement(self):
        from money_agent.monitoring import ingest_observation

        experiment_id = self.add_experiment()
        evidence = {
            "experiment_id": experiment_id,
            "source_kind": "analytics_readonly",
            "metric": "qualified runs",
            "value": 4,
            "evidence_ref": "analytics:event-4",
            "observed_at": 1000,
        }

        first = ingest_observation(**evidence)
        second = ingest_observation(**evidence)

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.store.list_observations(experiment_id)), 1)
        experiment = self.store.get_experiment(experiment_id)
        self.assertEqual(experiment["status"], "measuring")
        self.assertNotIn("revenue", experiment["result"].lower())

    def test_revenue_requires_payment_or_owner_evidence(self):
        from money_agent.monitoring import MonitoringError, ingest_observation

        experiment_id = self.add_experiment()
        with self.assertRaises(MonitoringError):
            ingest_observation(
                experiment_id=experiment_id,
                source_kind="analytics_readonly",
                metric="qualified runs",
                value=1,
                revenue_usd=79,
                evidence_ref="analytics:not-a-payment",
                observed_at=1000,
            )

    def test_unknown_or_mismatched_source_fails_closed(self):
        from money_agent.monitoring import MonitoringError, ingest_observation

        experiment_id = self.add_experiment()
        for source in ("unknown", "payment_provider_readonly"):
            with self.subTest(source=source), self.assertRaises(MonitoringError):
                ingest_observation(
                    experiment_id=experiment_id,
                    source_kind=source,
                    metric="qualified runs",
                    value=1,
                    evidence_ref=f"{source}:1",
                    observed_at=1000,
                )


if __name__ == "__main__":
    unittest.main()
