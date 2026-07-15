"""Send a best-effort HOI4 CI result notification to Discord."""

from __future__ import annotations

import http.client
import json
import os
import uuid
from pathlib import Path
from urllib import error, parse, request


PASS_COLOR = 0x2DA44E
FAIL_COLOR = 0xD1242F


def build_payload(environ: dict[str, str]) -> dict[str, object]:
    status = environ.get("HOI4_CI_JOB_STATUS", "unknown").lower()
    passed = status == "success"
    details = [f"Workflow status: **{status.upper()}**"]
    summary = load_summary(environ.get("HOI4_CI_REPORT", ""))
    if "errors" in summary and "warnings" in summary:
        details.append(
            f"Diagnostics: **{summary['errors']} error(s)**, "
            f"**{summary['warnings']} warning(s)**"
        )

    server_url = environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    repository = environ.get("GITHUB_REPOSITORY", "unknown")
    run_id = environ.get("GITHUB_RUN_ID", "")
    sha = environ.get("GITHUB_SHA", "")
    run_url = f"{server_url}/{repository}/actions/runs/{run_id}"
    commit_url = f"{server_url}/{repository}/commit/{sha}"

    return {
        "username": "HOI4 CI",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": (
                    f"{environ.get('HOI4_CI_JOB_NAME', 'HOI4 CI')}: "
                    f"{'PASS' if passed else 'FAIL'}"
                ),
                "url": run_url,
                "description": "\n".join(details),
                "color": PASS_COLOR if passed else FAIL_COLOR,
                "fields": [
                    {
                        "name": "Repository",
                        "value": repository,
                        "inline": True,
                    },
                    {
                        "name": "Ref",
                        "value": environ.get("GITHUB_REF_NAME", "unknown"),
                        "inline": True,
                    },
                    {
                        "name": "Commit",
                        "value": f"[`{sha[:7] or 'unknown'}`]({commit_url})",
                        "inline": True,
                    },
                ],
            }
        ],
    }


def load_summary(report: str) -> dict[str, object]:
    if not report:
        return {}
    try:
        payload = json.loads(Path(report).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    summary = payload.get("summary", {})
    return summary if isinstance(summary, dict) else {}


def webhook_url_with_wait(webhook_url: str) -> str:
    parts = parse.urlsplit(webhook_url)
    query = dict(parse.parse_qsl(parts.query, keep_blank_values=True))
    query["wait"] = "true"
    return parse.urlunsplit(parts._replace(query=parse.urlencode(query)))


def encode_request(
    payload: dict[str, object], report: Path | None
) -> tuple[bytes, str]:
    payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if report is None:
        return payload_bytes, "application/json"

    boundary = f"----hoi4-ci-{uuid.uuid4().hex}"
    body = bytearray()

    def add_part(headers: list[str], content: bytes) -> None:
        body.extend(f"--{boundary}\r\n".encode())
        for header in headers:
            body.extend(f"{header}\r\n".encode())
        body.extend(b"\r\n")
        body.extend(content)
        body.extend(b"\r\n")

    add_part(
        [
            'Content-Disposition: form-data; name="payload_json"',
            "Content-Type: application/json; charset=utf-8",
        ],
        payload_bytes,
    )
    add_part(
        [
            'Content-Disposition: form-data; name="files[0]"; '
            'filename="hoi4-ci-report.json"',
            "Content-Type: application/json",
        ],
        report.read_bytes(),
    )
    body.extend(f"--{boundary}--\r\n".encode())
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def report_to_attach(environ: dict[str, str]) -> Path | None:
    if environ.get("HOI4_CI_JOB_STATUS", "").lower() == "success":
        return None
    report = environ.get("HOI4_CI_REPORT", "")
    if not report:
        return None
    path = Path(report)
    return path if path.is_file() else None


def main() -> int:
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not webhook_url:
        print("DISCORD_WEBHOOK_URL is not configured; skipping Discord notification.")
        return 0

    environ = dict(os.environ)
    try:
        data, content_type = encode_request(
            build_payload(environ), report_to_attach(environ)
        )
        webhook_request = request.Request(
            webhook_url_with_wait(webhook_url),
            data=data,
            headers={"Content-Type": content_type},
            method="POST",
        )
        with request.urlopen(webhook_request, timeout=15) as response:
            response.read()
    except error.HTTPError as exc:
        print(f"::warning title=Discord notification failed::HTTP {exc.code}")
    except (OSError, error.URLError, ValueError, http.client.HTTPException):
        print("::warning title=Discord notification failed::Request could not be sent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
