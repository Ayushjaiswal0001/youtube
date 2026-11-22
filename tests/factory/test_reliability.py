"""Reliability primitives (T49): journals, locks, preflight, retries, cleanup, manifests.

Each test here corresponds to a way unattended production actually breaks: a state machine that
records an impossible history, a lock nobody can release, a retry that repeats a permanent failure,
a cleanup that deletes the finished video, a truncated MP4 that looks complete.
"""

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from factory import reliability as rel


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.journal = rel.JobJournal("job1", root=Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_fresh_journal_has_no_state(self):
        self.assertIsNone(self.journal.state())
        self.assertEqual(self.journal.records(), [])

    def test_states_are_recorded_in_order(self):
        self.journal.transition("PREFLIGHT")
        self.journal.transition("GENERATING")
        self.journal.transition("RENDERING")
        self.assertEqual([r["state"] for r in self.journal.records()],
                         ["PREFLIGHT", "GENERATING", "RENDERING"])
        self.assertEqual(self.journal.state(), "RENDERING")

    def test_an_illegal_transition_is_rejected(self):
        self.journal.transition("PREFLIGHT")
        with self.assertRaises(rel.InvalidTransition):
            self.journal.transition("PUBLISHED")
        self.assertEqual(self.journal.state(), "PREFLIGHT")

    def test_a_failed_job_can_be_retried(self):
        self.journal.transition("PREFLIGHT")
        self.journal.transition("RENDERING")
        self.journal.transition("FAILED", error="boom")
        self.assertEqual(self.journal.state(), "FAILED")
        self.journal.transition("RECOVERABLE")
        self.journal.transition("RENDERING")
        self.assertEqual(self.journal.attempts(), 1)

    def test_a_torn_final_line_does_not_hide_the_history(self):
        self.journal.transition("PREFLIGHT")
        self.journal.transition("GENERATING")
        with self.journal.journal.open("a", encoding="utf-8") as handle:
            handle.write('{"state": "RENDER')  # a kill during write
        self.assertEqual([r["state"] for r in self.journal.records()],
                         ["PREFLIGHT", "GENERATING"])

    def test_the_snapshot_mirrors_the_journal(self):
        self.journal.transition("PREFLIGHT", disk={"free_mb": 10})
        snapshot = json.loads(self.journal.snapshot_path.read_text(encoding="utf-8"))
        self.assertEqual(snapshot["state"], "PREFLIGHT")
        self.assertEqual(snapshot["disk"]["free_mb"], 10)

    def test_every_declared_state_is_reachable_from_somewhere(self):
        declared = set(rel.JOB_STATES)
        reachable = {"QUEUED"} | {to for edges in rel.ALLOWED_TRANSITIONS.values() for to in edges}
        self.assertEqual(declared - reachable, set())


class LockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "locks" / "chan_plan.lock"

    def tearDown(self):
        self.tmp.cleanup()

    def test_one_owner_at_a_time(self):
        first = rel.JobLock(self.path, job_id="a")
        self.assertTrue(first.acquire())
        self.assertFalse(rel.JobLock(self.path, job_id="b").acquire())
        first.release()

    def test_the_next_owner_can_take_the_lock(self):
        first = rel.JobLock(self.path, job_id="a")
        first.acquire()
        first.release()
        self.assertTrue(rel.JobLock(self.path, job_id="b").acquire())

    def test_a_context_manager_releases_on_exception(self):
        with self.assertRaises(RuntimeError):
            with rel.JobLock(self.path, job_id="a"):
                raise RuntimeError("render died")
        self.assertFalse(self.path.exists())

    def test_a_holding_job_blocks_the_context_manager(self):
        holder = rel.JobLock(self.path, job_id="a")
        holder.acquire()
        with self.assertRaises(rel.LockBusy):
            with rel.JobLock(self.path, job_id="b"):
                pass
        holder.release()

    def test_a_dead_process_lock_is_stale(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({
            "pid": 999_999_999, "host": rel.socket.gethostname(),
            "acquired_at": "2026-01-01T00:00:00+00:00", "job_id": "dead",
            "heartbeat": time.time(),
        }), encoding="utf-8")
        self.assertTrue(rel.JobLock(self.path, job_id="new").is_stale())

    def test_an_old_heartbeat_is_stale(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({
            "pid": os.getpid(), "host": "somewhere-else",
            "acquired_at": "2026-01-01T00:00:00+00:00", "job_id": "slow",
            "heartbeat": time.time() - 10_000,
        }), encoding="utf-8")
        self.assertTrue(rel.JobLock(self.path, job_id="new", ttl=900).is_stale())

    def test_a_live_lock_with_a_fresh_heartbeat_is_not_stale(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({
            "pid": os.getpid(), "host": rel.socket.gethostname(),
            "acquired_at": "2026-01-01T00:00:00+00:00", "job_id": "live",
            "heartbeat": time.time(),
        }), encoding="utf-8")
        self.assertFalse(rel.JobLock(self.path, job_id="new", ttl=900).is_stale())

    def test_a_stale_lock_is_taken_over(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({
            "pid": 999_999_999, "host": rel.socket.gethostname(),
            "acquired_at": "2026-01-01T00:00:00+00:00", "job_id": "dead",
            "heartbeat": time.time(),
        }), encoding="utf-8")
        self.assertTrue(rel.JobLock(self.path, job_id="new").acquire())

    def test_a_heartbeat_extends_the_lock(self):
        lock = rel.JobLock(self.path, job_id="a", ttl=60)
        lock.acquire()
        first = lock.read().heartbeat
        # Windows advances time.time() in ~15.6 ms ticks, so two heartbeats in the same tick are
        # legitimately identical. The TTL is 900 s; the test only has to cross one tick.
        time.sleep(0.05)
        lock.heartbeat()
        self.assertGreater(lock.read().heartbeat, first)
        lock.release()

    def test_a_foreign_lock_is_not_deleted_by_its_previous_owner(self):
        # A lock stolen after a false-stale must not be removed by the original holder's cleanup.
        stolen = rel.JobLock(self.path, job_id="a")
        stolen.acquire()
        self.path.write_text(json.dumps({
            "pid": os.getpid(), "host": rel.socket.gethostname(),
            "acquired_at": "2026-01-01T00:00:00+00:00", "job_id": "b",
            "heartbeat": time.time(),
        }), encoding="utf-8")
        stolen.release()
        self.assertTrue(self.path.exists())


class PreflightTests(unittest.TestCase):
    def test_a_working_machine_passes(self):
        report = rel.preflight(channels=("natkhat-toons",))
        self.assertTrue(report.ok, report.to_dict())
        names = {c["name"] for c in report.checks}
        self.assertTrue({"ffmpeg", "ffprobe", "fonts_dir", "devanagari_font"} <= names)

    def test_a_missing_channel_is_a_failure(self):
        report = rel.preflight(channels=("not-a-channel",))
        self.assertFalse(report.ok)
        self.assertIn("channel_configs", report.to_dict()["failed"])

    def test_too_little_disk_is_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = rel.preflight(disk_paths=[Path(tmp)], reserve_mb=10 ** 9)
        self.assertFalse(report.ok)
        self.assertTrue(any(name.startswith("disk:") for name in report.to_dict()["failed"]))

    def test_fonts_are_optional_for_non_character_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = rel.preflight(disk_paths=[Path(tmp)], require_fonts=False)
        self.assertNotIn("devanagari_font", {c["name"] for c in report.checks})


class ClassificationTests(unittest.TestCase):
    def test_network_errors_are_transient(self):
        self.assertEqual(rel.classify_failure(ConnectionResetError("reset")), "transient")
        self.assertEqual(rel.classify_failure("ffmpeg timed out"), "transient")
        self.assertEqual(rel.classify_failure("HTTP 503"), "transient")

    def test_content_errors_are_permanent(self):
        self.assertEqual(rel.classify_failure(ValueError("unknown channel x")), "permanent")
        self.assertEqual(rel.classify_failure("no scenes matched [7]"), "permanent")
        self.assertEqual(rel.classify_failure("HTTP 403 forbidden"), "permanent")

    def test_something_unrecognised_is_unknown(self):
        self.assertEqual(rel.classify_failure(RuntimeError("weird thing")), "unknown")


class RetryTests(unittest.TestCase):
    def test_a_transient_failure_is_retried_and_then_succeeds(self):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise ConnectionResetError("reset by peer")
            return "ok"

        policy = rel.RetryPolicy(attempts=3, base_delay=0, sleep=lambda _: None)
        self.assertEqual(policy.call(flaky), "ok")
        self.assertEqual(calls["n"], 3)

    def test_a_permanent_failure_is_not_retried(self):
        calls = {"n": 0}

        def broken():
            calls["n"] += 1
            raise ValueError("no scenes matched")

        policy = rel.RetryPolicy(attempts=5, base_delay=0, sleep=lambda _: None)
        with self.assertRaises(ValueError):
            policy.call(broken)
        self.assertEqual(calls["n"], 1)

    def test_retries_are_bounded(self):
        calls = {"n": 0}

        def always_transient():
            calls["n"] += 1
            raise TimeoutError("timed out")

        policy = rel.RetryPolicy(attempts=3, base_delay=0, sleep=lambda _: None)
        with self.assertRaises(TimeoutError):
            policy.call(always_transient)
        self.assertEqual(calls["n"], 3)

    def test_backoff_grows_then_plateaus(self):
        policy = rel.RetryPolicy(attempts=5, base_delay=2, max_delay=10)
        self.assertEqual([policy.delay_for(n) for n in (1, 2, 3, 4, 5)],
                         [2, 4, 8, 10, 10])

    def test_the_retry_callback_sees_each_attempt(self):
        seen = []
        policy = rel.RetryPolicy(attempts=3, base_delay=0, sleep=lambda _: None)
        state = {"n": 0}

        def flaky():
            state["n"] += 1
            if state["n"] < 3:
                raise TimeoutError("slow")
            return 1

        policy.call(flaky, on_retry=lambda attempt, exc: seen.append(attempt))
        self.assertEqual(seen, [1, 2])


class ProcessTests(unittest.TestCase):
    def test_a_hung_child_is_killed_at_the_timeout(self):
        with self.assertRaises(TimeoutError):
            rel.run_process(["python", "-c", "import time; time.sleep(30)"], timeout=0.5)

    def test_a_normal_child_returns_its_output(self):
        result = rel.run_process(["python", "-c", "print('hello')"], timeout=30)
        self.assertEqual(result.returncode, 0)
        self.assertIn("hello", result.stdout)


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "video.mp4").write_bytes(b"\0" * 20_000)
        (self.root / "video.partial.mp4").write_bytes(b"\0" * 1000)
        (self.root / "scene_001.mp4.tmp").write_bytes(b"\0" * 1000)
        old = time.time() - 7_200
        for path in self.root.iterdir():
            os.utime(path, (old, old))

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_disposable_files_are_removed(self):
        removed = rel.sweep_disposable(self.root, older_than=3600)
        names = {Path(item).name for item in removed}
        self.assertIn("video.partial.mp4", names)
        self.assertIn("scene_001.mp4.tmp", names)
        self.assertNotIn("video.mp4", names)
        self.assertTrue((self.root / "video.mp4").is_file())

    def test_recent_disposables_are_left_alone(self):
        fresh = self.root / "just_now.partial.mp4"
        fresh.write_bytes(b"\0" * 100)
        removed = rel.sweep_disposable(self.root, older_than=3600)
        self.assertNotIn(str(fresh), removed)


class IntegrityTests(unittest.TestCase):
    def test_a_missing_file_is_not_complete(self):
        self.assertFalse(rel.media_is_complete("/nonexistent/video.mp4"))

    def test_a_truncated_file_is_not_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "video.mp4"
            path.write_bytes(b"\0" * 50_000)
            self.assertFalse(rel.media_is_complete(path))

    def test_a_real_mp4_is_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ok.mp4"
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                 "color=c=black:s=320x240:d=1:r=30", "-f", "lavfi", "-i",
                 "sine=frequency=440:duration=1", "-shortest", "-pix_fmt", "yuv420p",
                 str(path)], check=True, capture_output=True)
            self.assertTrue(rel.media_is_complete(path))


class ManifestTests(unittest.TestCase):
    def test_the_manifest_hashes_every_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "video.mp4"
            video.write_bytes(b"\0" * 20_000)
            captions = root / "captions.srt"
            captions.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
            manifest = rel.production_manifest(
                channel="c", plan_id="p", engine="shorts", format="shorts",
                artifacts={"video": video, "captions": captions},
                qc={"ok": True, "checks": [{"name": "x", "ok": True}]},
            )
        names = {entry["name"] for entry in manifest["artifacts"]}
        self.assertEqual(names, {"video", "captions"})
        video_entry = next(e for e in manifest["artifacts"] if e["name"] == "video")
        self.assertEqual(len(video_entry["sha256"]), 64)
        self.assertFalse(video_entry["complete"])  # zeros are not a decodable MP4
        self.assertTrue(manifest["qc"]["ok"])

    def test_a_missing_artifact_is_omitted_not_faked(self):
        manifest = rel.production_manifest(
            channel="c", plan_id="p", engine="shorts", format="shorts",
            artifacts={"video": Path("/nope/video.mp4")})
        self.assertEqual(manifest["artifacts"], [])


if __name__ == "__main__":
    unittest.main()
