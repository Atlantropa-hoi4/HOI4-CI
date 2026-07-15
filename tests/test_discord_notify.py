from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).parents[1] / "discord-notify" / "send.py"
SPEC = importlib.util.spec_from_file_location("discord_notify", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
discord_notify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(discord_notify)


class DiscordNotifyTests(unittest.TestCase):
    def test_payload_contains_result_context_and_diagnostic_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.json"
            report.write_text(
                json.dumps({"summary": {"errors": 2, "warnings": 1}}),
                encoding="utf-8",
            )
            environ = {
                "HOI4_CI_JOB_NAME": "Smoke checks",
                "HOI4_CI_JOB_STATUS": "failure",
                "HOI4_CI_REPORT": str(report),
                "GITHUB_SERVER_URL": "https://github.example",
                "GITHUB_REPOSITORY": "example/mod",
                "GITHUB_RUN_ID": "123",
                "GITHUB_REF_NAME": "main",
                "GITHUB_SHA": "0123456789abcdef",
            }

            payload = discord_notify.build_payload(environ)

        embed = payload["embeds"][0]
        self.assertEqual(embed["title"], "Smoke checks: FAIL")
        self.assertEqual(
            embed["url"],
            "https://github.example/example/mod/actions/runs/123",
        )
        self.assertIn("2 error(s)", embed["description"])
        self.assertEqual(payload["allowed_mentions"], {"parse": []})

    def test_failure_report_is_encoded_as_multipart_attachment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.json"
            report.write_text('{"summary": {}}\n', encoding="utf-8")

            body, content_type = discord_notify.encode_request(
                {"embeds": [{"title": "FAIL"}]}, report
            )

        self.assertTrue(content_type.startswith("multipart/form-data; boundary="))
        self.assertIn(b'name="payload_json"', body)
        self.assertIn(b'name="files[0]"', body)
        self.assertIn(b'filename="hoi4-ci-report.json"', body)
        self.assertIn(b'{"summary": {}}', body)

    def test_success_does_not_attach_report(self) -> None:
        environ = {
            "HOI4_CI_JOB_STATUS": "success",
            "HOI4_CI_REPORT": "unused.json",
        }

        self.assertIsNone(discord_notify.report_to_attach(environ))

    def test_wait_parameter_preserves_existing_query(self) -> None:
        url = discord_notify.webhook_url_with_wait(
            "https://discord.example/webhook?thread_id=456"
        )

        self.assertEqual(
            url,
            "https://discord.example/webhook?thread_id=456&wait=true",
        )

    def test_main_posts_success_payload(self) -> None:
        environ = {
            "DISCORD_WEBHOOK_URL": "https://discord.example/webhook/token",
            "HOI4_CI_JOB_NAME": "Smoke checks",
            "HOI4_CI_JOB_STATUS": "success",
            "GITHUB_REPOSITORY": "example/mod",
            "GITHUB_RUN_ID": "123",
            "GITHUB_SHA": "0123456789abcdef",
        }
        with (
            mock.patch.dict(discord_notify.os.environ, environ, clear=True),
            mock.patch.object(discord_notify.request, "urlopen") as urlopen,
        ):
            response = urlopen.return_value.__enter__.return_value
            response.read.return_value = b"{}"

            exit_code = discord_notify.main()

        self.assertEqual(exit_code, 0)
        webhook_request = urlopen.call_args.args[0]
        self.assertEqual(
            webhook_request.full_url,
            "https://discord.example/webhook/token?wait=true",
        )
        self.assertEqual(
            webhook_request.get_header("Content-type"), "application/json"
        )
        self.assertEqual(
            webhook_request.get_header("User-agent"),
            discord_notify.USER_AGENT,
        )
        payload = json.loads(webhook_request.data)
        self.assertEqual(payload["embeds"][0]["title"], "Smoke checks: PASS")


if __name__ == "__main__":
    unittest.main()
