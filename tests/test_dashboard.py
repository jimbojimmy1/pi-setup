import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


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
        os.environ.pop("MA_EXPECTED_RELEASE_REF", None)
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

    def test_state_exposes_inbox_counts_and_latest_availability_without_file_details(self):
        artifacts = self.root / "artifacts"
        inbox = artifacts / "observation-inbox"
        for name in ("incoming", "processing", "accepted", "rejected"):
            directory = inbox / name
            directory.mkdir(parents=True)
            (directory / f"secret-{name}.json").write_text(
                '{"private_payload":"must-not-appear"}', encoding="utf-8"
            )
        (inbox / "incoming" / "ignored.tmp").write_text("partial", encoding="utf-8")

        experiment_id = self.store.list_experiments()[0]["id"]
        self.store.add_observation(
            experiment_id=experiment_id,
            source_kind="public_http",
            metric="public_availability",
            value=1,
            revenue_usd=0,
            evidence_ref="public-health:private-ref",
            observed_at=1500,
        )

        import money_agent.app as app_module

        app_module = importlib.reload(app_module)
        with patch.object(app_module.time, "time", return_value=2100):
            response = app_module.app.test_client().get("/api/state")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(
            payload["inbox"],
            {"incoming": 1, "processing": 1, "accepted": 1, "rejected": 1},
        )
        self.assertEqual(
            payload["availability"],
            {"available": True, "observed_at": 1500.0, "age": "10m ago"},
        )
        body = response.get_data(as_text=True)
        self.assertNotIn("secret-incoming.json", body)
        self.assertNotIn("must-not-appear", body)
        self.assertNotIn("private-ref", body)

    def test_template_renders_inbox_and_availability_summaries(self):
        template = (
            Path(__file__).resolve().parents[1]
            / "money_agent"
            / "templates"
            / "index.html"
        ).read_text(encoding="utf-8")

        self.assertIn("INBOX EVIDENCE", template)
        for name in ("incoming", "processing", "accepted", "rejected"):
            self.assertIn(f"d.inbox.{name}", template)
        self.assertIn("PUBLIC AVAILABILITY", template)
        self.assertIn("available", template)
        self.assertIn("unavailable", template)

    def _add_checkout_experiment(self):
        idea_id = self.store.add_idea("FunnelSleuth checkout readiness")
        return self.store.add_experiment(
            idea_id=idea_id,
            project="FunnelSleuth",
            action_kind="checkout_readiness_check",
            hypothesis="The public page exposes checkout.",
            deliverable="Inspect the public page.",
            metric="checkout_readiness",
            stop_condition="Keep the owner blocker until ready.",
            window_days=30,
            autonomy_class="AUTO_LOCAL",
            hours=0,
            cost_usd=0,
            measurement_source="public_http:https://example.com/offers",
        )

    def _state(self, now=2100):
        import money_agent.app as app_module

        app_module = importlib.reload(app_module)
        with patch.object(app_module.time, "time", return_value=now):
            response = app_module.app.test_client().get("/api/state")
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def test_missing_or_zero_checkout_evidence_keeps_project_blocker(self):
        experiment_id = self._add_checkout_experiment()

        missing = self._state()
        self.assertEqual(
            missing["checkout_readiness"],
            [
                {
                    "project": "FunnelSleuth",
                    "ready": None,
                    "observed_at": None,
                    "age": "never",
                }
            ],
        )
        self.assertTrue(
            any(
                blocker["action"]
                == "Connect the existing Stripe or PayPal checkout link."
                for blocker in missing["owner_blockers"]
            )
        )

        self.store.add_observation(
            experiment_id=experiment_id,
            source_kind="public_http",
            metric="checkout_readiness",
            value=0,
            revenue_usd=0,
            evidence_ref="checkout-readiness:zero",
            observed_at=1500,
        )
        zero = self._state()
        self.assertFalse(zero["checkout_readiness"][0]["ready"])
        self.assertEqual(zero["checkout_readiness"][0]["age"], "10m ago")
        self.assertTrue(
            any("checkout link" in blocker["action"] for blocker in zero["owner_blockers"])
        )

    def test_positive_matching_checkout_evidence_clears_only_link_blocker(self):
        experiment_id = self._add_checkout_experiment()
        self.store.add_observation(
            experiment_id=experiment_id,
            source_kind="public_http",
            metric="checkout_readiness",
            value=1,
            revenue_usd=0,
            evidence_ref="checkout-readiness:ready",
            observed_at=1500,
        )

        payload = self._state()

        self.assertTrue(payload["checkout_readiness"][0]["ready"])
        self.assertFalse(
            any("checkout link" in blocker["action"] for blocker in payload["owner_blockers"])
        )

    def test_template_renders_checkout_status_without_payment_claim(self):
        template = (
            Path(__file__).resolve().parents[1]
            / "money_agent"
            / "templates"
            / "index.html"
        ).read_text(encoding="utf-8")

        self.assertIn("CHECKOUT READINESS", template)
        self.assertIn("d.checkout_readiness", template)
        self.assertIn("checkout link detected", template)
        self.assertIn("checkout link not detected", template)
        self.assertIn("no checkout evidence", template)
        self.assertIn("not a payment", template)

    def _release_state(self, installed=None, expected=None):
        marker = self.root / "release.txt"
        if installed is not None:
            marker.write_text(installed, encoding="utf-8")
        elif marker.exists():
            marker.unlink()

        import money_agent.app as app_module

        app_module = importlib.reload(app_module)
        environment = {"MA_EXPECTED_RELEASE_REF": expected} if expected else {}
        with patch.dict(os.environ, environment, clear=False), patch.object(
            app_module, "RELEASE_MARKER", marker
        ):
            response = app_module.app.test_client().get("/api/state")
        self.assertEqual(response.status_code, 200)
        return response.get_json()["runtime_release"]

    def test_runtime_release_reports_clean_match_and_mismatch(self):
        revision = "6452753bc32f1eebc05cf9e3170f21e481a030ad"

        self.assertEqual(
            self._release_state(revision + "\n", revision[:12]),
            {
                "installed": revision,
                "expected": revision[:12],
                "status": "current",
            },
        )
        self.assertEqual(
            self._release_state(revision, "ae02000"),
            {
                "installed": revision,
                "expected": "ae02000",
                "status": "outdated",
            },
        )

    def test_runtime_release_fails_closed_for_dirty_missing_or_invalid_markers(self):
        revision = "6452753bc32f1eebc05cf9e3170f21e481a030ad"
        self.assertEqual(
            self._release_state(revision + "-dirty", revision),
            {
                "installed": revision + "-dirty",
                "expected": revision,
                "status": "dirty",
            },
        )
        self.assertEqual(
            self._release_state(None, revision),
            {"installed": None, "expected": revision, "status": "unknown"},
        )
        self.assertEqual(
            self._release_state("../../secret\n", revision),
            {"installed": None, "expected": revision, "status": "unknown"},
        )
        self.assertEqual(
            self._release_state("local-unversioned", "local-unversioned"),
            {
                "installed": "local-unversioned",
                "expected": "local-unversioned",
                "status": "unknown",
            },
        )
        self.assertEqual(
            self._release_state("main", "main"),
            {"installed": "main", "expected": "main", "status": "unknown"},
        )

    def test_template_renders_runtime_release_without_deployment_claim(self):
        template = (
            Path(__file__).resolve().parents[1]
            / "money_agent"
            / "templates"
            / "index.html"
        ).read_text(encoding="utf-8")

        self.assertIn("RUNTIME RELEASE", template)
        self.assertIn("d.runtime_release", template)
        for status in ("current", "outdated", "dirty", "unknown"):
            self.assertIn(status, template)


if __name__ == "__main__":
    unittest.main()
