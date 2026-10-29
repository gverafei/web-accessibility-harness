"""Backfill acquisition evidence from existing Axe artifacts.

Run inside the web container after the acquisition metadata columns exist.
The operation is idempotent and only visits completed rows without metadata.
"""

import json
import os
from urllib.parse import urlsplit

from database import get_connection
from main import app


CHALLENGE_MARKERS = (
    "security verification", "verify you are human", "checking your browser",
    "just a moment", "attention required", "captcha", "access denied",
)
MOVED_MARKERS = ("we have moved", "site has moved", "moved permanently")


def hostname(value):
    return (urlsplit(value or "").hostname or "").lower().removeprefix("www.")


def main():
    with app.app_context():
        connection = get_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, url, axe_wcag_violations AS axe_violations, dom_nodes, axe_raw_path, screenshot_path
            FROM experiment_results
            WHERE status='completed' AND acquisition_signals IS NULL
            """
        )
        updated = 0
        for row in cursor.fetchall():
            raw_path = row.get("axe_raw_path")
            captured_url = None
            raw_text = ""
            if raw_path and os.path.isfile(raw_path):
                try:
                    with open(raw_path, "r", encoding="utf-8") as artifact:
                        raw_text = artifact.read()
                    captured_url = json.loads(raw_text).get("url")
                except (OSError, UnicodeError, json.JSONDecodeError):
                    raw_text = ""
            review_text = raw_text.casefold()
            signals = []
            if captured_url and hostname(captured_url) != hostname(row.get("url")):
                signals.append("cross_domain_redirect")
            captured_path = (urlsplit(captured_url or "").path or "").casefold()
            challenge_path = any(
                marker in captured_path
                for marker in ("verify", "verification", "captcha", "challenge", "blocked")
            )
            if challenge_path or (
                int(row.get("dom_nodes") or 0) <= 150
                and any(marker in review_text for marker in CHALLENGE_MARKERS)
            ):
                signals.append("security_challenge")
            if any(marker in review_text for marker in MOVED_MARKERS):
                signals.append("moved_notice")
            if row.get("axe_violations") == 0:
                signals.append("zero_axe_issues")
            if not row.get("screenshot_path") or not os.path.isfile(row["screenshot_path"]):
                signals.append("screenshot_missing")
            cursor.execute(
                """
                UPDATE experiment_results
                SET captured_url=%s, acquisition_signals=%s
                WHERE id=%s
                """,
                (captured_url, json.dumps(signals), row["id"]),
            )
            updated += 1
        connection.commit()
        cursor.close()
        connection.close()
        print(f"Updated {updated} result(s).")


if __name__ == "__main__":
    main()
