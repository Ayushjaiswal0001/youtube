"""Plan generation and continuity tests.

These cover the autonomy layer: topic banks, series memory, batch merging and the
publishing gates. They do not render video, so they run without ffmpeg, Chrome or
network access.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import factory.content.plans as plans_module
import factory.content.script as script_module
import factory.state as state_module
from factory.config import CONTENT_DIR, load_channel_specs, selected_channels
from factory.content.plans import (
    PlanGenerationError,
    advance_after_publish,
    bank_status,
    existing_plan,
    generate_plan,
    next_natkhat_plan,
)
from factory.content.script import build_english_script, build_hindi_script, load_plans_for
from factory.state import ChannelState


class WorkspaceTestCase(unittest.TestCase):
    """Isolated copy of content/ plus a throwaway state root."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="factory-plans-"))
        self.content = self.tmp / "content"
        shutil.copytree(CONTENT_DIR, self.content)
        self.state_root = self.tmp / "state"
        self.state_root.mkdir()

        self._patches = [
            mock.patch.object(plans_module, "CONTENT_DIR", self.content),
            mock.patch.object(plans_module, "TOPICS_DIR", self.content / "topics"),
            mock.patch.object(plans_module, "SERIES_DIR", self.content / "series"),
            mock.patch.object(script_module, "CONTENT_DIR", self.content),
            mock.patch.object(state_module, "STATE_ROOT", self.state_root),
        ]
        for patch in self._patches:
            patch.start()

        self.specs = load_channel_specs()

    def tearDown(self) -> None:
        for patch in reversed(self._patches):
            patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def state(self, slug: str) -> ChannelState:
        return ChannelState(slug, root=self.state_root)


class TopicBankTests(WorkspaceTestCase):
    def test_every_banked_topic_satisfies_script_invariants(self) -> None:
        for slug in ("nexus-node", "academic-biohacker"):
            spec = self.specs[slug]
            for plan in load_plans_for(spec):
                script = build_english_script(spec, plan)
                self.assertGreaterEqual(script.metadata["word_count"], 60, plan["id"])
                self.assertLessEqual(script.metadata["word_count"], 140, plan["id"])
                self.assertGreaterEqual(len(script.sources), 2, plan["id"])

    def test_generated_plan_is_written_to_batch(self) -> None:
        spec = self.specs["nexus-node"]
        first = generate_plan(spec)
        self.assertTrue(first["created"])
        batch = json.loads(Path(first["batch"]).read_text(encoding="utf-8"))
        ids = [item["id"] for item in batch["channels"]["nexus-node"]]
        self.assertIn(first["plan_id"], ids)

        # English channels build a backlog: every call claims the next unused topic.
        second = generate_plan(spec)
        self.assertTrue(second["created"])
        self.assertNotEqual(second["plan_id"], first["plan_id"])

    def test_natkhat_plan_generation_is_idempotent(self) -> None:
        spec = self.specs["natkhat-toons"]
        first = generate_plan(spec, allow_unpublished=True)
        self.assertTrue(first["created"])
        again = generate_plan(spec, allow_unpublished=True)
        self.assertFalse(again["created"])
        self.assertEqual(again["plan_id"], first["plan_id"])

    def test_successive_plans_never_repeat_a_topic(self) -> None:
        spec = self.specs["nexus-node"]
        seen: list[str] = []
        for _ in range(3):
            result = generate_plan(spec)
            self.assertTrue(result["created"], result)
            seen.append(result["plan_id"])
        self.assertEqual(len(seen), len(set(seen)))

    def test_exhausted_bank_fails_loudly(self) -> None:
        spec = self.specs["academic-biohacker"]
        with self.assertRaises(PlanGenerationError) as caught:
            for _ in range(100):
                generate_plan(spec)
        self.assertIn("exhausted", str(caught.exception))

    def test_bank_status_reports_remaining_topics(self) -> None:
        spec = self.specs["nexus-node"]
        status = bank_status(spec)
        self.assertEqual(status["mode"], "topics")
        self.assertEqual(status["plans_written"], len(load_plans_for(spec)))
        self.assertEqual(status["remaining"], len(status["unused_topics"]))


class SeriesContinuityTests(WorkspaceTestCase):
    def test_first_episode_of_a_new_series_is_allowed(self) -> None:
        plan = generate_plan(self.specs["natkhat-toons"], allow_unpublished=True)["plan"]
        self.assertEqual(plan["episode"], 4)
        self.assertEqual(plan["series"], "natkhat-haveli")
        self.assertEqual(plan["id"], "natkhat-haveli-e4")

    def test_out_of_order_episode_is_blocked(self) -> None:
        """The guarantee is about episodes the factory produced. `start_episode: 4` says 1-3 are an earlier
        batch published outside the factory, so their absence from history must not block episode 4 - which is
        the state a brand-new channel is in, and it made the channel unable to start at all. What must block is
        an episode this factory rendered and has not published.
        """

        spec = self.specs["natkhat-toons"]
        state = self.state(spec.slug)
        state.root.mkdir(parents=True, exist_ok=True)
        (state.root / "series.json").write_text(
            json.dumps({"active_series": "natkhat-haveli", "next_episode": 5}), encoding="utf-8")
        state.record(
            topic="previous",
            title="previous",
            status="rendered",
            plan_id="natkhat-haveli-e4",
        )
        with self.assertRaises(PlanGenerationError) as caught:
            next_natkhat_plan(spec, state)
        self.assertIn("natkhat-haveli-e4", str(caught.exception))
        self.assertIn("not uploaded", str(caught.exception))
        self.assertEqual(caught.exception.kind, "blocked")

    def test_a_channel_with_no_factory_history_starts_at_its_first_authored_episode(self) -> None:
        spec = self.specs["natkhat-toons"]
        plan = next_natkhat_plan(spec, self.state(spec.slug))
        self.assertEqual(plan["id"], "natkhat-haveli-e4")

    def test_previous_episode_uploaded_unblocks_the_next(self) -> None:
        spec = self.specs["natkhat-toons"]
        state = self.state(spec.slug)
        state.record(
            topic="previous",
            title="previous",
            status="uploaded",
            plan_id="natkhat-haveli-e3",
            video_id="abc123",
        )
        plan = next_natkhat_plan(spec, state)
        self.assertEqual(plan["episode"], 4)

    def test_rendered_but_not_uploaded_still_blocks(self) -> None:
        spec = self.specs["natkhat-toons"]
        state = self.state(spec.slug)
        state.record(topic="previous", title="previous", status="rendered", plan_id="natkhat-haveli-e3")
        with self.assertRaises(PlanGenerationError):
            next_natkhat_plan(spec, state)

    def test_publish_advances_the_series_pointer(self) -> None:
        spec = self.specs["natkhat-toons"]
        state = self.state(spec.slug)
        state.record(topic="prev", title="prev", status="uploaded", plan_id="natkhat-haveli-e3")

        plan = next_natkhat_plan(spec, state)
        payload = advance_after_publish(spec, plan)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["next_episode"], 5)
        self.assertEqual(payload["active_series"], "natkhat-haveli")

    def test_finished_series_rolls_over_to_the_next_one(self) -> None:
        spec = self.specs["natkhat-toons"]
        state = self.state(spec.slug)
        state.save_series(
            {
                "active_series": "natkhat-haveli",
                "next_episode": 6,
                "completed": [],
            }
        )
        state.record(topic="prev", title="prev", status="uploaded", plan_id="natkhat-haveli-e5")
        last = next_natkhat_plan(spec, state)
        self.assertEqual(last["id"], "natkhat-haveli-e6")

        payload = advance_after_publish(spec, last)
        self.assertEqual(payload["active_series"], "")
        self.assertIn("natkhat-haveli", payload["completed"])

        state.record(topic="last", title="last", status="uploaded", plan_id="natkhat-haveli-e6")
        following = next_natkhat_plan(spec, state)
        self.assertEqual(following["series"], "natkhat-jungle")
        self.assertEqual(following["episode"], 1)

    def test_hindi_plan_builds_a_valid_script(self) -> None:
        spec = self.specs["natkhat-toons"]
        plan = next_natkhat_plan(spec, self.state(spec.slug), allow_unpublished=True)
        script = build_hindi_script(spec, plan)
        self.assertGreaterEqual(len(script.lines), 3)
        self.assertEqual(script.episode, 4)
        self.assertTrue(script.series_title)


class BatchMergeTests(WorkspaceTestCase):
    def test_plans_from_older_batches_are_not_lost(self) -> None:
        spec = self.specs["nexus-node"]
        original = {plan["id"] for plan in load_plans_for(spec)}
        new_batch = self.content / "batch_2026-12-01.json"
        new_batch.write_text(
            json.dumps(
                {
                    "batch_id": "later",
                    "channels": {"nexus-node": [{"id": "later-topic", "title": "Later"}]},
                }
            ),
            encoding="utf-8",
        )
        ids = {plan["id"] for plan in load_plans_for(spec)}
        self.assertTrue(original.issubset(ids))
        self.assertIn("later-topic", ids)

    def test_duplicate_ids_across_batches_are_deduplicated(self) -> None:
        spec = self.specs["nexus-node"]
        clone = self.content / "batch_2026-12-02.json"
        source = json.loads((self.content / "batch_2026-11-20.json").read_text(encoding="utf-8"))
        clone.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
        ids = [plan["id"] for plan in load_plans_for(spec)]
        self.assertEqual(len(ids), len(set(ids)))

    def test_existing_plan_lookup_is_slug_insensitive(self) -> None:
        spec = self.specs["nexus-node"]
        self.assertIsNotNone(existing_plan(spec, "Nexus-Data-Wall"))
        self.assertIsNone(existing_plan(spec, "nope"))


class ChannelSelectionTests(unittest.TestCase):
    def test_comma_separated_channels_are_supported(self) -> None:
        specs = load_channel_specs()
        chosen = selected_channels("nexus-node,natkhat-toons", specs)
        self.assertEqual([spec.slug for spec in chosen], ["nexus-node", "natkhat-toons"])

    def test_unknown_channel_still_raises(self) -> None:
        with self.assertRaises(ValueError):
            selected_channels("nexus-node,ghost", load_channel_specs())


class StatePlanIdTests(unittest.TestCase):
    def test_plan_id_is_persisted_and_queryable(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="factory-state-"))
        try:
            state = ChannelState("nexus-node", root=tmp)
            state.record(topic="t", title="T", status="uploaded", plan_id="nexus-data-wall")
            self.assertEqual(state.plan_status("nexus-data-wall"), "uploaded")
            self.assertIsNone(state.plan_status("missing"))
            entry = state.history()[0]
            self.assertEqual(entry["plan_id"], "nexus-data-wall")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
