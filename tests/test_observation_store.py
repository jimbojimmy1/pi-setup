import importlib
import os
from pathlib import Path
import tempfile
import unittest


class ObservationStoreTest(unittest.TestCase):
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

    def add_experiment(self):
        idea_id = self.store.add_idea("Measured experiment")
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
            measurement_source="analytics_readonly",
        )

    def test_duplicate_evidence_is_idempotent(self):
        experiment_id = self.add_experiment()

        first = self.store.add_observation(
            experiment_id=experiment_id,
            source_kind="analytics_readonly",
            metric="qualified runs",
            value=3,
            revenue_usd=0,
            evidence_ref="analytics:event-123",
            observed_at=1000,
        )
        second = self.store.add_observation(
            experiment_id=experiment_id,
            source_kind="analytics_readonly",
            metric="qualified runs",
            value=3,
            revenue_usd=0,
            evidence_ref="analytics:event-123",
            observed_at=1000,
        )

        self.assertEqual(first, second)
        observations = self.store.list_observations(experiment_id)
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]["value"], 3)

    def test_status_and_result_update_together(self):
        experiment_id = self.add_experiment()

        self.store.update_experiment_status(
            experiment_id,
            "measuring",
            result="Latest verified metric: 3 qualified runs.",
        )

        experiment = self.store.get_experiment(experiment_id)
        self.assertEqual(experiment["status"], "measuring")
        self.assertEqual(
            experiment["result"], "Latest verified metric: 3 qualified runs."
        )

    def test_verified_revenue_summary_counts_only_deduplicated_payment_evidence(self):
        experiment_id = self.add_experiment()
        second_experiment_id = self.add_experiment()

        observations = (
            (experiment_id, "payment_provider_readonly", 79, "payment:79", 1000),
            (second_experiment_id, "payment_provider_readonly", 79, "payment:79", 1100),
            (experiment_id, "owner_verified", 299, "owner:299", 1500),
            (experiment_id, "analytics_readonly", 999, "analytics:not-revenue", 2000),
            (experiment_id, "public_http", 888, "public:not-revenue", 2500),
            (experiment_id, "owner_verified", 0, "owner:zero", 3000),
        )
        for (
            target_experiment_id,
            source_kind,
            revenue_usd,
            evidence_ref,
            observed_at,
        ) in observations:
            self.store.add_observation(
                experiment_id=target_experiment_id,
                source_kind=source_kind,
                metric="qualified runs",
                value=1,
                revenue_usd=revenue_usd,
                evidence_ref=evidence_ref,
                observed_at=observed_at,
            )

        connection = self.store.conn()
        for revenue_usd, evidence_ref, observed_at in (
            ("garbage", "owner:garbage", 3500),
            (79, "", 3600),
            (float("inf"), "owner:infinity", 3700),
            (79, "owner:bad-time", "later"),
            (79, b"owner:binary-ref", 3800),
        ):
            connection.execute(
                "INSERT INTO observations(experiment_id,source_kind,metric,value,"
                "revenue_usd,evidence_ref,observed_at,created_at)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (
                    experiment_id,
                    "owner_verified",
                    "qualified runs",
                    1,
                    revenue_usd,
                    evidence_ref,
                    observed_at,
                    1,
                ),
            )
        connection.execute(
            "INSERT INTO observations(experiment_id,source_kind,metric,value,"
            "revenue_usd,evidence_ref,observed_at,created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (
                second_experiment_id,
                "owner_verified",
                "qualified runs",
                1,
                float("inf"),
                "owner:299",
                999999,
                1,
            ),
        )
        connection.commit()

        self.assertEqual(
            self.store.verified_revenue_summary(),
            {"total_usd": 378.0, "payments": 2, "last_observed_at": 1500.0},
        )

    def test_existing_experiment_table_gains_measurement_source(self):
        connection = self.store.conn()
        connection.execute("DROP TABLE experiments")
        connection.execute(
            "CREATE TABLE experiments("
            "id INTEGER PRIMARY KEY, status TEXT NOT NULL, updated_at REAL NOT NULL)"
        )
        connection.commit()

        self.store.init()

        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(experiments)").fetchall()
        }
        self.assertIn("measurement_source", columns)


if __name__ == "__main__":
    unittest.main()
