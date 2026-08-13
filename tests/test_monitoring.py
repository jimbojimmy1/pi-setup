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
            "https://example.com/\r\nInjected: yes",
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

    def test_positive_metric_can_mark_a_non_health_experiment_won(self):
        from money_agent.monitoring import ingest_observation

        experiment_id = self.add_experiment()

        ingest_observation(
            experiment_id=experiment_id,
            source_kind="analytics_readonly",
            metric="qualified runs",
            value=4,
            evidence_ref="analytics:won-4",
            observed_at=1000,
            outcome="won",
        )

        self.assertEqual(self.store.get_experiment(experiment_id)["status"], "won")
        self.assertEqual(
            [event["event_type"] for event in self.store.experiment_events(experiment_id)][-1],
            "won",
        )
        self.assertTrue(self.store.lessons())

    def test_lost_requires_completed_window_and_no_payment(self):
        from money_agent.monitoring import MonitoringError, ingest_observation

        experiment_id = self.add_experiment()
        base = {
            "experiment_id": experiment_id,
            "source_kind": "analytics_readonly",
            "metric": "qualified runs",
            "value": 0,
            "evidence_ref": "analytics:window-end",
            "observed_at": 1000,
            "outcome": "lost",
        }
        with self.assertRaises(MonitoringError):
            ingest_observation(**base)

        ingest_observation(**base, window_complete=True)

        self.assertEqual(self.store.get_experiment(experiment_id)["status"], "lost")

    def test_terminal_outcome_requires_positive_evidence_and_cannot_conflict(self):
        from money_agent.monitoring import MonitoringError, ingest_observation

        experiment_id = self.add_experiment()
        with self.assertRaises(MonitoringError):
            ingest_observation(
                experiment_id=experiment_id,
                source_kind="analytics_readonly",
                metric="qualified runs",
                value=0,
                evidence_ref="analytics:zero-win",
                observed_at=1000,
                outcome="won",
            )
        ingest_observation(
            experiment_id=experiment_id,
            source_kind="analytics_readonly",
            metric="qualified runs",
            value=2,
            evidence_ref="analytics:win",
            observed_at=1001,
            outcome="won",
        )
        with self.assertRaises(MonitoringError):
            ingest_observation(
                experiment_id=experiment_id,
                source_kind="analytics_readonly",
                metric="qualified runs",
                value=0,
                evidence_ref="analytics:conflict",
                observed_at=1002,
                outcome="lost",
                window_complete=True,
            )

    def test_public_health_cannot_create_terminal_outcomes(self):
        from money_agent.monitoring import MonitoringError, ingest_observation

        experiment_id = self.add_experiment(
            measurement_source="public_http:https://example.com/health"
        )
        with self.assertRaises(MonitoringError):
            ingest_observation(
                experiment_id=experiment_id,
                source_kind="public_http",
                metric="qualified runs",
                value=1,
                evidence_ref="health:200",
                observed_at=1000,
                outcome="won",
            )

    def add_health_experiment(self):
        idea_id = self.store.add_idea("Public availability")
        return self.store.add_experiment(
            idea_id=idea_id,
            project="FunnelSleuth",
            action_kind="public_health_check",
            hypothesis="The public page remains reachable.",
            deliverable="Check the owned public page.",
            metric="public_availability",
            stop_condition="Escalate after repeated unavailability.",
            window_days=30,
            autonomy_class="AUTO_LOCAL",
            hours=0,
            cost_usd=0,
            measurement_source="public_http:https://example.com/health?probe=1",
        )

    def test_probe_uses_validated_ip_and_follows_no_redirects(self):
        from money_agent.monitoring import probe_public_https

        calls = []

        def resolver(host, port, type=0):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.35", port)),
            ]

        def connector(host, address, path, timeout, max_response_bytes):
            calls.append((host, address, path, timeout, max_response_bytes))
            return 302

        result = probe_public_https(
            "https://example.com/health?probe=1",
            resolver=resolver,
            connector=connector,
            timeout=7,
            max_response_bytes=2048,
        )

        self.assertEqual(result["status"], 302)
        self.assertTrue(result["available"])
        self.assertEqual(
            calls,
            [("example.com", "93.184.216.34", "/health?probe=1", 7, 2048)],
        )

    def test_checkout_detector_accepts_only_recognized_https_destinations(self):
        from money_agent.monitoring import checkout_provider_from_html

        accepted = {
            '<a href="https://buy.stripe.com/live_123">Buy</a>': "stripe",
            '<form action="https://book.stripe.com/book_123"></form>': "stripe",
            '<a href="https://donate.stripe.com/give_123">Give</a>': "stripe",
            '<a href="https://paypal.me/FunnelSleuth/79">Pay</a>': "paypal",
            '<a href="https://www.paypal.com/ncp/payment/ABC123">Pay</a>': "paypal",
        }
        for html, provider in accepted.items():
            with self.subTest(html=html):
                self.assertEqual(checkout_provider_from_html(html), provider)

        rejected = (
            "Stripe and PayPal accepted here",
            '<script>location="https://buy.stripe.com/not-a-link"</script>',
            '<a href="http://buy.stripe.com/insecure">Buy</a>',
            '<a href="https://buy.stripe.com.evil.example/phish">Buy</a>',
            '<a href="https://www.paypal.com/us/home">PayPal</a>',
            '<a href="/checkout">Checkout</a>',
        )
        for html in rejected:
            with self.subTest(html=html):
                self.assertIsNone(checkout_provider_from_html(html))

    def test_checkout_probe_is_one_bounded_get_without_redirect_follow(self):
        from money_agent.monitoring import probe_checkout_readiness

        calls = []

        def resolver(host, port, type=0):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

        def connector(host, address, path, timeout, max_response_bytes):
            calls.append((host, address, path, timeout, max_response_bytes))
            return 200, "text/html; charset=utf-8", (
                b'<a href="https://buy.stripe.com/live_123">Buy</a>'
            )

        result = probe_checkout_readiness(
            "https://example.com/offers?source=home",
            resolver=resolver,
            connector=connector,
            timeout=99,
            max_response_bytes=999_999,
        )

        self.assertEqual(
            calls,
            [("example.com", "93.184.216.34", "/offers?source=home", 30, 65_536)],
        )
        self.assertEqual(
            result,
            {
                "url": "https://example.com/offers?source=home",
                "status": 200,
                "ready": True,
                "provider": "stripe",
            },
        )

    def test_checkout_collection_is_hourly_and_never_reports_revenue(self):
        from money_agent.monitoring import collect_checkout_readiness

        idea_id = self.store.add_idea("Checkout readiness")
        experiment_id = self.store.add_experiment(
            idea_id=idea_id,
            project="FunnelSleuth",
            action_kind="checkout_readiness_check",
            hypothesis="The public offer exposes checkout.",
            deliverable="Check the public offer page.",
            metric="checkout_readiness",
            stop_condition="Keep the owner blocker until ready.",
            window_days=30,
            autonomy_class="AUTO_LOCAL",
            hours=0,
            cost_usd=0,
            measurement_source="public_http:https://example.com/offers",
        )

        def resolver(host, port, type=0):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

        calls = []

        def connector(host, address, path, timeout, max_response_bytes):
            calls.append(address)
            return 200, "text/html", b'<a href="https://paypal.me/store/79">Pay</a>'

        first = collect_checkout_readiness(
            experiment_id, now=7201, resolver=resolver, connector=connector
        )
        second = collect_checkout_readiness(
            experiment_id, now=7250, resolver=resolver, connector=connector
        )

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["value"], 1)
        self.assertEqual(first["revenue_usd"], 0)
        self.assertEqual(calls, ["93.184.216.34"])

    def test_health_collection_is_one_availability_observation_per_bucket(self):
        from money_agent.monitoring import collect_public_health

        experiment_id = self.add_health_experiment()
        calls = []

        def resolver(host, port, type=0):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

        def connector(host, address, path, timeout, max_response_bytes):
            calls.append(address)
            return 200

        first = collect_public_health(
            experiment_id,
            now=7201,
            bucket_seconds=3600,
            resolver=resolver,
            connector=connector,
        )
        second = collect_public_health(
            experiment_id,
            now=7250,
            bucket_seconds=3600,
            resolver=resolver,
            connector=connector,
        )

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(calls, ["93.184.216.34"])
        self.assertEqual(first["value"], 1)
        self.assertEqual(first["revenue_usd"], 0)
        self.assertEqual(self.store.get_experiment(experiment_id)["status"], "measuring")

    def test_health_failure_records_zero_without_closing_experiment(self):
        from money_agent.monitoring import collect_public_health

        experiment_id = self.add_health_experiment()

        def resolver(host, port, type=0):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

        def connector(host, address, path, timeout, max_response_bytes):
            raise TimeoutError("offline")

        observation = collect_public_health(
            experiment_id,
            now=10801,
            resolver=resolver,
            connector=connector,
        )

        self.assertEqual(observation["value"], 0)
        self.assertEqual(self.store.get_experiment(experiment_id)["status"], "measuring")


if __name__ == "__main__":
    unittest.main()
