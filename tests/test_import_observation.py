import importlib
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest


class ObservationImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        os.environ["MA_DB"] = str(self.root / "money.db")
        import money_agent.store as store

        self.store = importlib.reload(store)
        self.store.init()
        idea_id = self.store.add_idea("Imported measurement")
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

    def valid_payload(self):
        return {
            "experiment_id": self.experiment_id,
            "source_kind": "analytics_readonly",
            "metric": "qualified runs",
            "value": 3,
            "evidence_ref": "analytics:event-3",
            "observed_at": 1000,
        }

    def test_parser_accepts_only_the_exact_typed_contract(self):
        from money_agent.import_observation import ImportError, parse_payload

        parsed = parse_payload(json.dumps(self.valid_payload()))
        self.assertEqual(parsed["experiment_id"], self.experiment_id)
        self.assertEqual(parsed["revenue_usd"], 0)
        self.assertIsNone(parsed["outcome"])
        self.assertFalse(parsed["window_complete"])

        invalid_payloads = []
        for key in self.valid_payload():
            missing = self.valid_payload()
            missing.pop(key)
            invalid_payloads.append(missing)
        invalid_payloads.extend(
            [
                {**self.valid_payload(), "api_key": "must-not-leak"},
                {**self.valid_payload(), "experiment_id": True},
                {**self.valid_payload(), "value": "3"},
                {**self.valid_payload(), "window_complete": 1},
                {**self.valid_payload(), "outcome": "profit"},
            ]
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(ImportError):
                parse_payload(json.dumps(payload))

    def test_parser_rejects_oversized_input(self):
        from money_agent.import_observation import ImportError, parse_payload

        with self.assertRaises(ImportError):
            parse_payload(" " * 65537)

    def test_cli_imports_from_stdin_without_echoing_payload(self):
        from money_agent.import_observation import main

        stdout = StringIO()
        stderr = StringIO()
        code = main(
            ["-"],
            input_stream=StringIO(json.dumps(self.valid_payload())),
            output_stream=stdout,
            error_stream=stderr,
        )

        self.assertEqual(code, 0)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["experiment_id"], self.experiment_id)
        self.assertEqual(result["status"], "measuring")
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(len(self.store.list_observations(self.experiment_id)), 1)

    def test_cli_reads_a_named_file_and_returns_generic_errors(self):
        from money_agent.import_observation import main

        path = self.root / "observation.json"
        path.write_text(json.dumps(self.valid_payload()), encoding="utf-8")
        stdout = StringIO()
        stderr = StringIO()
        self.assertEqual(
            main(
                [str(path)],
                input_stream=StringIO(),
                output_stream=stdout,
                error_stream=stderr,
            ),
            0,
        )

        secret = "secret-value-that-must-not-echo"
        bad = json.dumps({**self.valid_payload(), "api_key": secret})
        stdout = StringIO()
        stderr = StringIO()
        code = main(
            ["-"],
            input_stream=StringIO(bad),
            output_stream=stdout,
            error_stream=stderr,
        )
        self.assertEqual(code, 2)
        self.assertNotIn(secret, stderr.getvalue())
        self.assertEqual(stdout.getvalue(), "")

    def test_cli_applies_an_evidence_backed_terminal_outcome(self):
        from money_agent.import_observation import main

        payload = {
            **self.valid_payload(),
            "value": 2,
            "evidence_ref": "analytics:won",
            "outcome": "won",
        }
        stdout = StringIO()
        code = main(
            ["-"],
            input_stream=StringIO(json.dumps(payload)),
            output_stream=stdout,
            error_stream=StringIO(),
        )

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["status"], "won")


if __name__ == "__main__":
    unittest.main()
