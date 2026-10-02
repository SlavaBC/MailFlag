"""Tests for persistent latency diagnostics without GUI or IMAP."""

import json
from pathlib import Path
import tempfile
import unittest

from mailflag.core.diagnostics import (
    DiagnosticLog, format_report, latest_delivery_summary, read_events,
)


class DiagnosticsTests(unittest.TestCase):
    def test_jsonl_write_read_and_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "diagnostics.jsonl"
            log = DiagnosticLog(path, clock=lambda: 100.25)
            log.write("status_ok", "a@example.test", seconds=0.12, uidnext=43)
            events = read_events(path)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["event"], "status_ok")
            self.assertEqual(events[0]["uidnext"], 43)
            report = format_report(path)
            self.assertIn("status_ok [a@example.test]", report)
            self.assertIn("seconds=0.12", report)

    def test_rotation_preserves_previous_log(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "diagnostics.jsonl"
            log = DiagnosticLog(path, max_bytes=140, clock=lambda: 100.0)
            log.write("first", detail="x" * 70)
            log.write("second", detail="y" * 70)
            previous = path.with_suffix(".jsonl.1")
            self.assertTrue(previous.is_file())
            self.assertEqual(read_events(path)[-1]["event"], "second")
            self.assertEqual(json.loads(previous.read_text())["event"], "first")

    def test_latest_delivery_timing_summary(self):
        events = [
            {"epoch": 100.0, "event": "status_ok", "account": "a",
             "uidnext_changed": True},
            {"epoch": 100.2, "event": "message_parsed", "account": "a",
             "uid": 42, "kind": "otp", "header_age_seconds": 121.0},
            {"epoch": 100.25, "event": "ui_dispatch", "account": "a",
             "uid": 42},
        ]
        summary = latest_delivery_summary(events)
        self.assertIn("header-to-parse=121.0s", summary)
        self.assertIn("imap-to-parse=0.2s", summary)
        self.assertIn("parse-to-ui=0.05s", summary)


if __name__ == "__main__":
    unittest.main()
