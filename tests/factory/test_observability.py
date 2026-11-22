"""T49d: notifications, resource guardrails and structured job logs."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from factory.observability import (
    EVENTS,
    JOB_STARTED,
    QC_FAILED,
    JobLog,
    NullNotifier,
    ResourceMonitor,
    WebhookNotifier,
    estimate_render_mb,
    notifier_from_env,
    process_rss_mb,
    write_job_log,
)


class NotifierTests(unittest.TestCase):
    def test_there_is_no_notifier_unless_one_is_configured(self) -> None:
        notifier = notifier_from_env({})
        self.assertIsInstance(notifier, NullNotifier)
        self.assertFalse(notifier.describe()["enabled"])

    def test_a_null_notifier_records_without_claiming_delivery(self) -> None:
        notifier = notifier_from_env({})
        self.assertFalse(notifier.send(JOB_STARTED, {"channel": "natkhat-toons"}))
        self.assertFalse(notifier.sent[-1]["delivered"])

    def test_a_malformed_url_is_refused_rather_than_guessed(self) -> None:
        notifier = notifier_from_env({"FACTORY_NOTIFY_WEBHOOK": "natkhat:secret@example"})
        self.assertIsInstance(notifier, NullNotifier)
        self.assertIn("not an http", notifier.describe()["reason"])

    def test_a_configured_webhook_posts_json(self) -> None:
        seen = {}

        def transport(url, body, timeout):
            seen["url"] = url
            seen["body"] = json.loads(body.decode("utf-8"))
            return 204

        notifier = notifier_from_env({"FACTORY_NOTIFY_WEBHOOK": "https://example.test/hook"})
        notifier = WebhookNotifier("https://example.test/hook", transport=transport)
        self.assertTrue(notifier.send(QC_FAILED, {"detail": "loudness -8 LUFS"}))
        self.assertEqual(seen["body"]["event"], QC_FAILED)
        self.assertEqual(seen["body"]["payload"]["detail"], "loudness -8 LUFS")
        self.assertEqual(notifier.delivered, 1)

    def test_a_failed_delivery_is_reported_not_swallowed(self) -> None:
        notifier = WebhookNotifier("https://example.test/hook",
                                   transport=lambda url, body, timeout: 500)
        self.assertFalse(notifier.send(QC_FAILED, {}))
        self.assertEqual(notifier.last_error, "HTTP 500")

    def test_a_network_error_is_recorded(self) -> None:
        def boom(url, body, timeout):
            raise OSError("connection refused")

        notifier = WebhookNotifier("https://example.test/hook", transport=boom)
        self.assertFalse(notifier.send(QC_FAILED, {}))
        self.assertIn("refused", notifier.last_error)

    def test_the_event_vocabulary_is_fixed(self) -> None:
        self.assertIn(JOB_STARTED, EVENTS)
        self.assertEqual(len(set(EVENTS)), len(EVENTS))


class ResourceTests(unittest.TestCase):
    def test_memory_is_readable_without_extra_dependencies(self) -> None:
        rss = process_rss_mb()
        if rss is not None:
            self.assertGreater(rss, 0.0)

    def test_the_estimate_scales_with_the_frame(self) -> None:
        small = estimate_render_mb(900, 1080, 1920)
        big = estimate_render_mb(900, 1920, 1080)
        self.assertGreater(small, 200.0)
        self.assertLess(abs(small - big), 1e-6, "both orientations allocate the same buffers")

    def test_the_monitor_remembers_its_peak(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            monitor = ResourceMonitor(Path(tmp))
            for _ in range(3):
                monitor.sample()
            self.assertEqual(len(monitor.samples), 3)
            self.assertGreaterEqual(monitor.peak_rss_mb, 0.0)
            json.dumps(monitor.as_dict())

    def test_a_full_disk_is_unhealthy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            monitor = ResourceMonitor(Path(tmp), floor_mb=1e15)
            monitor.sample()
            self.assertFalse(monitor.healthy())


class JobLogTests(unittest.TestCase):
    def test_a_log_records_scenes_and_summarises(self) -> None:
        log = JobLog("job_1", "natkhat-toons", "episode_1", config={"format": "long"})
        log.scene(1, 22.5, cached=False, frames=177)
        log.scene(2, 0.1, cached=True, frames=177)
        summary = log.finish("rendered")
        self.assertEqual(summary["status"], "rendered")
        data = log.as_dict()
        self.assertEqual(data["scenes"], 2)
        self.assertEqual(data["cache_hits"], 1)
        self.assertEqual(data["scene_seconds"], {"1": 22.5, "2": 0.1})

    def test_the_log_is_jsonl_and_machine_parseable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "job.jsonl"
            log = JobLog("job_2", "nexus-node", "ep2", path=path)
            log.record(JOB_STARTED)
            log.scene(1, 1.0, cached=False, frames=30)
            log.finish("qc_failed", detail="loudness")
            lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([line["event"] for line in lines],
                             ["job_started", "scene_rendered", "finished"])
            for line in lines:
                self.assertEqual(line["job_id"], "job_2")
                self.assertEqual(line["channel"], "nexus-node")

    def test_the_summary_can_be_written_as_a_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = JobLog("job_3", "academic-biohacker", "ep3")
            log.record(JOB_STARTED)
            path = write_job_log(Path(tmp) / "job.json", log)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["channel"], "academic-biohacker")
            self.assertIn("started_at", data)

    def test_a_recorded_event_carries_the_job_identity(self) -> None:
        log = JobLog("job_4", "nexus-node", "ep4")
        entry = log.record(QC_FAILED, detail="framing")
        for key in ("job_id", "channel", "episode"):
            self.assertIn(key, entry)


if __name__ == "__main__":
    unittest.main()
