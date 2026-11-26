"""Reliability primitives (T49): journals, locks, preflight, retries, cleanup, manifests.

Each test here corresponds to a way unattended production actually breaks: a state machine that
records an impossible history, a lock nobody can release, a retry that repeats a permanent failure,
a cleanup that deletes the finished video, a truncated MP4 that looks complete.
"""

import json
import multiprocessing
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


def _lock_contender(path, ready, start, finish, results, job_id):
    lock = rel.JobLock(path, job_id=job_id, heartbeat_interval=0.05)
    ready.set()
    if not start.wait(20):
        results.put(("timeout", None, os.getpid()))
        return
    acquired = lock.acquire()
    results.put(("acquired" if acquired else "busy", lock.owner_token, os.getpid()))
    if acquired:
        finish.wait(20)
        lock.release()


def _lock_owner_wait(path, acquired, *, abrupt=False):
    lock = rel.JobLock(path, job_id="same-job", heartbeat_interval=30)
    if not lock.acquire():
        os._exit(3)
    acquired.set()
    if abrupt:
        os._exit(0)
    while True:
        time.sleep(1)


def _lock_reclaimer_race(path, precheck_done, proceed, results):
    original_try_lock = rel._try_native_lock

    def delayed_try_lock(fd):
        precheck_done.set()
        if not proceed.wait(20):
            raise TimeoutError("replacement owner was not created")
        return original_try_lock(fd)

    rel._try_native_lock = delayed_try_lock
    lock = rel.JobLock(path, job_id="reclaimer", heartbeat_interval=30)
    acquired = lock.acquire()
    results.put(("acquired" if acquired else "busy", lock.owner_token))
    if acquired:
        lock.release()


class LockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "locks" / "chan_plan.lock"

    def tearDown(self):
        self.tmp.cleanup()

    def _contenders(self, count, *, job_id="same-job"):
        ctx = multiprocessing.get_context("spawn")
        start = ctx.Event()
        finish = ctx.Event()
        ready = [ctx.Event() for _ in range(count)]
        results = ctx.Queue()
        processes = [
            ctx.Process(
                target=_lock_contender,
                args=(str(self.path), ready[index], start, finish, results, job_id),
            )
            for index in range(count)
        ]
        try:
            for process in processes:
                process.start()
            for event in ready:
                self.assertTrue(event.wait(20), "contender did not reach the start barrier")
            start.set()
            outcomes = [results.get(timeout=30) for _ in processes]
            finish.set()
            for process in processes:
                process.join(20)
                self.assertFalse(process.is_alive(), "contender did not exit")
                self.assertEqual(process.exitcode, 0)
            return outcomes
        finally:
            start.set()
            finish.set()
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(10)
            results.close()
            results.join_thread()

    def _write_legacy_record(self, *, pid, host=None, heartbeat=None):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({
            "pid": pid,
            "host": host or rel.socket.gethostname(),
            "acquired_at": "2026-01-01T00:00:00+00:00",
            "job_id": "legacy-job",
            "heartbeat": time.time() if heartbeat is None else heartbeat,
        }), encoding="utf-8")

    def test_one_owner_at_a_time(self):
        first = rel.JobLock(self.path, job_id="a")
        self.assertTrue(first.acquire())
        contender = rel.JobLock(self.path, job_id="b")
        self.assertFalse(contender.acquire())
        self.assertFalse(contender.is_stale())
        first.release()

    def test_the_next_owner_can_take_the_lock_without_deleting_guard(self):
        first = rel.JobLock(self.path, job_id="same-job")
        self.assertTrue(first.acquire())
        guard_identity = (self.path.with_name(self.path.name + ".guard").stat().st_dev,
                          self.path.with_name(self.path.name + ".guard").stat().st_ino)
        first.release()
        self.assertTrue(self.path.exists())
        self.assertTrue(self.path.with_name(self.path.name + ".guard").exists())

        second = rel.JobLock(self.path, job_id="same-job")
        self.assertTrue(second.acquire())
        self.assertNotEqual(first.owner_token, second.owner_token)
        current_guard = self.path.with_name(self.path.name + ".guard").stat()
        self.assertEqual(guard_identity, (current_guard.st_dev, current_guard.st_ino))
        second.release()

    def test_a_context_manager_releases_kernel_ownership_on_exception(self):
        with self.assertRaises(RuntimeError):
            with rel.JobLock(self.path, job_id="a"):
                raise RuntimeError("render died")
        self.assertTrue(self.path.exists())
        self.assertTrue(self.path.with_name(self.path.name + ".guard").exists())
        successor = rel.JobLock(self.path, job_id="b")
        self.assertTrue(successor.acquire())
        successor.release()

    def test_a_holding_job_blocks_the_context_manager(self):
        holder = rel.JobLock(self.path, job_id="a")
        self.assertTrue(holder.acquire())
        with self.assertRaises(rel.LockBusy):
            with rel.JobLock(self.path, job_id="b"):
                pass
        holder.release()

    def test_active_process_with_expired_heartbeat_is_not_stale(self):
        lock = rel.JobLock(self.path, job_id="live", ttl=0.01, heartbeat_interval=30)
        self.assertTrue(lock.acquire())
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["heartbeat"] = time.time() - 7200
        self.path.write_text(json.dumps(payload), encoding="utf-8")

        self.assertFalse(rel.JobLock(self.path, job_id="contender", ttl=0.01).is_stale())
        self.assertFalse(rel.JobLock(self.path, job_id="contender").acquire())
        lock.release()

    def test_an_active_render_cannot_expire_at_the_original_3600_second_ttl(self):
        lock = rel.JobLock(self.path, job_id="long-render", ttl=3600, heartbeat_interval=30)
        self.assertTrue(lock.acquire())
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["heartbeat"] = time.time() - 3601
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        time.sleep(0.03)

        self.assertFalse(rel.JobLock(self.path, job_id="second", ttl=3600).is_stale())
        self.assertFalse(rel.JobLock(self.path, job_id="second").acquire())
        lock.release()

    def test_a_render_longer_than_its_ttl_keeps_ownership(self):
        lock = rel.JobLock(self.path, job_id="long-render", ttl=0.08, heartbeat_interval=0.01)
        self.assertTrue(lock.acquire())
        first_heartbeat = lock.read().heartbeat
        time.sleep(0.25)
        lock.assert_healthy()
        self.assertFalse(rel.JobLock(self.path, job_id="second").acquire())
        self.assertGreater(lock.read().heartbeat, first_heartbeat)
        lock.release()

    def test_a_dead_legacy_process_with_stale_heartbeat_can_be_recovered(self):
        self._write_legacy_record(pid=999_999_999, heartbeat=time.time() - 7200)
        lock = rel.JobLock(self.path, job_id="recovered")
        self.assertTrue(lock.is_stale())
        self.assertTrue(lock.acquire())
        self.assertEqual(lock.read().protocol, rel.JobLock.PROTOCOL)
        lock.release()

    def test_remote_legacy_owner_is_not_declared_dead_from_local_uncertainty(self):
        self._write_legacy_record(
            pid=999_999_999,
            host="remote-runner",
            heartbeat=time.time() - 7200,
        )
        lock = rel.JobLock(self.path, job_id="local")
        self.assertFalse(lock.is_stale())
        self.assertFalse(lock.acquire())

    def test_two_simultaneous_stale_reclaimers_have_one_owner(self):
        self._write_legacy_record(pid=999_999_999, heartbeat=time.time() - 7200)
        outcomes = self._contenders(2)
        self.assertEqual(sum(result[0] == "acquired" for result in outcomes), 1)
        self.assertEqual(sum(result[0] == "busy" for result in outcomes), 1)

    def test_replacement_lock_created_during_stale_reclamation_stays_owned(self):
        self._write_legacy_record(pid=999_999_999, heartbeat=time.time() - 7200)
        ctx = multiprocessing.get_context("spawn")
        precheck_done, proceed = ctx.Event(), ctx.Event()
        results = ctx.Queue()
        reclaimer = ctx.Process(
            target=_lock_reclaimer_race,
            args=(str(self.path), precheck_done, proceed, results),
        )
        reclaimer.start()
        replacement = None
        try:
            self.assertTrue(precheck_done.wait(20), "reclaimer did not inspect stale metadata")
            replacement = rel.JobLock(self.path, job_id="replacement")
            self.assertTrue(replacement.acquire())
            replacement_token = replacement.owner_token
            proceed.set()
            self.assertEqual(results.get(timeout=20)[0], "busy")
            replacement.assert_healthy()
            self.assertEqual(replacement.read().owner_token, replacement_token)
        finally:
            proceed.set()
            if replacement is not None:
                replacement.release()
            reclaimer.join(20)
            if reclaimer.is_alive():
                reclaimer.terminate()
                reclaimer.join(10)
            results.close()
            results.join_thread()
        self.assertFalse(reclaimer.is_alive())
        self.assertEqual(reclaimer.exitcode, 0)

    def test_replacement_metadata_never_replaces_the_guard_instance(self):
        first = rel.JobLock(self.path, job_id="same-job", heartbeat_interval=30)
        self.assertTrue(first.acquire())
        guard = self.path.with_name(self.path.name + ".guard")
        original_identity = (guard.stat().st_dev, guard.stat().st_ino)
        first.heartbeat()
        self.assertEqual(original_identity, (guard.stat().st_dev, guard.stat().st_ino))
        self.assertFalse(rel.JobLock(self.path, job_id="same-job").acquire())
        first.release()
        self.assertTrue(guard.exists())

    def test_former_owner_cannot_release_a_successor_with_the_same_job_id(self):
        former = rel.JobLock(self.path, job_id="same-job")
        self.assertTrue(former.acquire())
        former_token = former.owner_token
        former.release()

        replacement = rel.JobLock(self.path, job_id="same-job")
        self.assertTrue(replacement.acquire())
        self.assertNotEqual(former_token, replacement.owner_token)
        former.release()
        replacement.assert_healthy()
        self.assertFalse(rel.JobLock(self.path, job_id="same-job").acquire())
        replacement.release()

    def test_two_processes_with_the_same_job_identity_have_one_owner(self):
        outcomes = self._contenders(2, job_id="identical-job-id")
        self.assertEqual(sum(result[0] == "acquired" for result in outcomes), 1)
        self.assertEqual(sum(result[0] == "busy" for result in outcomes), 1)

    def test_production_heartbeat_renews_during_lock_ownership(self):
        lock = rel.JobLock(self.path, job_id="render", ttl=0.2, heartbeat_interval=0.02)
        self.assertTrue(lock.acquire())
        first = lock.read().heartbeat
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and lock.read().heartbeat <= first:
            time.sleep(0.01)
        self.assertGreater(lock.read().heartbeat, first)
        lock.assert_healthy()
        lock.release()

    def test_heartbeat_failure_stops_renewal_and_keeps_lock_fail_closed(self):
        lock = rel.JobLock(self.path, job_id="render", heartbeat_interval=0.01)
        self.assertTrue(lock.acquire())
        with mock.patch.object(lock, "_write_metadata", side_effect=OSError("disk unavailable")):
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and lock._heartbeat_error is None:
                time.sleep(0.01)
            self.assertIsNotNone(lock._heartbeat_error)
            with self.assertRaises(rel.LockHeartbeatError):
                lock.assert_healthy()
            self.assertFalse(rel.JobLock(self.path, job_id="contender").acquire())
        lock.release()
        recovered = rel.JobLock(self.path, job_id="recovered")
        self.assertTrue(recovered.acquire())
        recovered.release()

    def test_owner_termination_releases_os_lock(self):
        ctx = multiprocessing.get_context("spawn")
        acquired = ctx.Event()
        process = ctx.Process(target=_lock_owner_wait, args=(str(self.path), acquired))
        process.start()
        try:
            self.assertTrue(acquired.wait(20))
            process.terminate()
            process.join(20)
            self.assertFalse(process.is_alive())
            recovered = rel.JobLock(self.path, job_id="after-terminate")
            self.assertTrue(recovered.acquire())
            recovered.release()
        finally:
            if process.is_alive():
                process.terminate()
                process.join(10)

    def test_abrupt_process_termination_releases_os_lock(self):
        ctx = multiprocessing.get_context("spawn")
        acquired = ctx.Event()
        process = ctx.Process(
            target=_lock_owner_wait,
            args=(str(self.path), acquired),
            kwargs={"abrupt": True},
        )
        process.start()
        process.join(20)
        self.assertFalse(process.is_alive())
        self.assertEqual(process.exitcode, 0)
        self.assertTrue(acquired.is_set())
        recovered = rel.JobLock(self.path, job_id="after-kill")
        self.assertTrue(recovered.acquire())
        recovered.release()

    def test_sigkill_releases_os_lock_for_recovery(self):
        ctx = multiprocessing.get_context("spawn")
        acquired = ctx.Event()
        process = ctx.Process(target=_lock_owner_wait, args=(str(self.path), acquired))
        process.start()
        try:
            self.assertTrue(acquired.wait(20))
            process.kill()
            process.join(20)
            self.assertFalse(process.is_alive())
            recovered = rel.JobLock(self.path, job_id="after-sigkill")
            self.assertTrue(recovered.acquire())
            recovered.release()
        finally:
            if process.is_alive():
                process.kill()
                process.join(10)

    def test_corrupt_metadata_does_not_steal_a_live_os_lock_and_recovers_after_exit(self):
        owner = rel.JobLock(self.path, job_id="owner", heartbeat_interval=30)
        self.assertTrue(owner.acquire())
        self.path.write_text("{corrupt", encoding="utf-8")
        self.assertFalse(rel.JobLock(self.path, job_id="contender").acquire())
        owner.release()

        recovered = rel.JobLock(self.path, job_id="recovered")
        self.assertTrue(recovered.acquire())
        self.assertEqual(recovered.read().owner_token, recovered.owner_token)
        recovered.release()

    def test_missing_lock_files_are_created_and_recoverable(self):
        lock = rel.JobLock(self.path, job_id="new")
        self.assertTrue(lock.acquire())
        lock.release()
        self.assertTrue(self.path.exists())
        self.assertTrue(self.path.with_name(self.path.name + ".guard").exists())
        again = rel.JobLock(self.path, job_id="again")
        self.assertTrue(again.acquire())
        again.release()

    @unittest.skipUnless(os.name == "nt", "native LockFileEx is exercised on Windows")
    def test_windows_lockfileex_serializes_competing_handles(self):
        first = rel.JobLock(self.path, job_id="windows")
        self.assertTrue(first.acquire())
        self.assertFalse(rel.JobLock(self.path, job_id="windows").acquire())
        first.release()
        successor = rel.JobLock(self.path, job_id="windows")
        self.assertTrue(successor.acquire())
        successor.release()

    @unittest.skipUnless(os.name == "posix", "native flock is exercised on POSIX")
    def test_posix_flock_serializes_competing_handles(self):
        first = rel.JobLock(self.path, job_id="posix")
        self.assertTrue(first.acquire())
        self.assertFalse(rel.JobLock(self.path, job_id="posix").acquire())
        first.release()
        successor = rel.JobLock(self.path, job_id="posix")
        self.assertTrue(successor.acquire())
        successor.release()

    def test_concurrent_acquisition_stress_never_has_two_owners(self):
        outcomes = self._contenders(12, job_id="stress-shared-job")
        owners = [result[1] for result in outcomes if result[0] == "acquired"]
        self.assertEqual(len(owners), 1)
        self.assertEqual(len(set(owners)), 1)
        self.assertEqual(sum(result[0] == "busy" for result in outcomes), 11)


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
