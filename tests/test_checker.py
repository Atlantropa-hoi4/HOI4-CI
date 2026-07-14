from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from hoi4_ci.checker import Checker
from hoi4_ci.cli import main


class RepositoryFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write(self, relative: str, text: str, *, bom: bool = False) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        data = text.encode("utf-8")
        if bom:
            data = b"\xef\xbb\xbf" + data
        path.write_bytes(data)
        return path

    def codes(self, result) -> list[str]:
        return [item.code for item in result.diagnostics]


class CheckerTests(RepositoryFixture):
    def test_valid_kaiserreich_style_structures_pass(self) -> None:
        self.write(
            "events/example.txt",
            """add_namespace = example
country_event = {
\tid = example.1
\toption = { country_event = { id = example.2 days = 1 } }
}
""",
        )
        self.write(
            "history/states/1 - Corsica.txt",
            "state = {\n\tid = 1\n\tprovinces = { 1 2 3 }\n}\n",
        )
        self.write(
            "map/strategicregions/1 - Southern England.txt",
            'strategic_region={\n\tid=1\n\tname="STRATEGICREGION_1"\n}\n',
        )
        self.write(
            "localisation/english/example_l_english.yml",
            "l_english:\n"
            ' example_key: "Value with an "internal quote""\n'
            ' versioned_key:0 "Value"\n',
            bom=True,
        )
        self.write("localisation/english/placeholder_l_english.yml", "", bom=True)

        result = Checker(self.root).run()

        self.assertTrue(result.passed)
        self.assertEqual(result.stats["event_definitions"], 1)
        self.assertEqual(result.stats["state_definitions"], 1)
        self.assertEqual(result.stats["strategic_region_definitions"], 1)
        self.assertEqual(result.stats["localisation_keys"], 2)

    def test_duplicate_event_id_ignores_nested_event_calls(self) -> None:
        self.write(
            "events/first.txt",
            """country_event = {
 id = sample.1
 option = { country_event = { id = sample.2 } }
}
""",
        )
        self.write(
            "events/second.txt",
            "country_event = { id = sample.1 option = { } }\n",
        )

        result = Checker(self.root).run(("duplicates",))

        self.assertEqual(self.codes(result), ["DUPLICATE_EVENT_ID"])
        self.assertEqual(result.stats["event_definitions"], 2)

    def test_localisation_policy_reports_bom_syntax_and_duplicate_keys(self) -> None:
        self.write(
            "localisation/english/first_l_english.yml",
            'l_english:\n same_key: "First"\n',
            bom=True,
        )
        self.write(
            "localisation/english/second_l_english.yml",
            'l_english:\n same_key: "Second"\n broken_key: "Never closed\n',
        )

        result = Checker(self.root).run(("localisation",))

        self.assertCountEqual(
            self.codes(result),
            [
                "LOCALISATION_BOM",
                "DUPLICATE_LOCALISATION_KEY",
                "LOCALISATION_SYNTAX",
            ],
        )

    def test_id_filename_mismatch_and_unbalanced_brace_are_reported(self) -> None:
        self.write("history/states/7 - Example.txt", "state = { id = 8 }\n")
        self.write(
            "map/strategicregions/9 - Example.txt",
            "strategic_region = { id = 9\n",
        )

        result = Checker(self.root).run(("duplicates",))

        self.assertCountEqual(
            self.codes(result),
            ["STATE_FILENAME_ID", "SCRIPT_UNBALANCED_BRACES"],
        )

    def test_invalid_utf8_is_reported_once_across_checks(self) -> None:
        path = self.root / "localisation/english/bad_l_english.yml"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"\xef\xbb\xbfl_english:\n bad: \"\xff\"\n")

        result = Checker(self.root).run()

        self.assertEqual(self.codes(result), ["TEXT_ENCODING"])

    def test_excluded_glob_is_not_scanned(self) -> None:
        path = self.root / "generated/bad.txt"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"\xff")

        result = Checker(self.root, excludes=("generated/**",)).run(("encoding",))

        self.assertTrue(result.passed)
        self.assertEqual(result.stats["text_files"], 0)


class CliTests(RepositoryFixture):
    def test_cli_writes_json_report(self) -> None:
        self.write(
            "localisation/english/example_l_english.yml",
            'l_english:\n key: "Value"\n',
            bom=True,
        )
        report_path = self.root.parent / f"{self.root.name}-report.json"
        self.addCleanup(report_path.unlink, missing_ok=True)

        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(
                [
                    str(self.root),
                    "--check",
                    "localisation",
                    "--json-report",
                    str(report_path),
                ]
            )

        self.assertEqual(exit_code, 0)
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertTrue(payload["summary"]["passed"])
        self.assertEqual(payload["stats"]["localisation_keys"], 1)


if __name__ == "__main__":
    unittest.main()
