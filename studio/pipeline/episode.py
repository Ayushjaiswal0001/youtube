"""Complete Episode Assembly Engine (Milestone M5 & M6).
Sequentially renders multi-scene episodes to conserve RAM, saves intermediate files,
supports resilient checkpoint resume with ffprobe verification, and concatenates scenes
into the final 1080x1920 Short.
"""

import sys
import json
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional

# Ensure UTF-8 output on Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from studio.config import EPISODES_DIR, INTERMEDIATE_DIR, LOGS_DIR
from studio.audio.tts_engine import TTSEngine
from studio.animation.scene_renderer import SceneRenderer
from studio.animation.transitions import plan_transitions
from studio.story_engine import StoryEngine


class EpisodePipeline:
    """Orchestrates end-to-end production of a 30-second animated short."""

    def __init__(self):
        self.story_engine = StoryEngine()
        self.tts = TTSEngine()
        self.renderer = SceneRenderer()

    def _verify_scene_mp4(self, scene_path: Path) -> bool:
        """Verifies that a scene MP4 exists, is non-empty (>10KB), and contains a valid video stream."""
        if not scene_path.exists():
            return False

        try:
            # File size check (> 10 KB)
            if scene_path.stat().st_size < 10240:
                return False

            # ffprobe stream inspection
            cmd = [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_name",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(scene_path)
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
            codec = res.stdout.strip()
            return codec in ("h264", "hevc", "mpeg4")
        except Exception:
            return False

    def produce_episode(self, story: Optional[Dict[str, Any]] = None,
                        force_template_idx: Optional[int] = None) -> Dict[str, Any]:
        """Runs the complete production pipeline from story to final video."""
        # 1. Story Generation / Validation
        if story is None:
            story = self.story_engine.generate_daily_story(force_template_idx=force_template_idx)

        story_id = story["story_id"]
        title = story["title"]
        print(f"\n[Pipeline] Starting Episode Production: {title} ({story_id})")

        episode_work_dir = INTERMEDIATE_DIR / story_id
        episode_work_dir.mkdir(parents=True, exist_ok=True)

        # Save project state file for resume capability
        project_file = episode_work_dir / "project.json"
        project_state = {
            "story": story,
            "completed_scenes": []
        }
        if project_file.exists():
            try:
                with open(project_file, "r", encoding="utf-8") as pf:
                    project_state = json.load(pf)
                    print(f"  [Resume] Found existing checkpoint with {len(project_state.get('completed_scenes', []))} completed scenes.")
            except Exception as e:
                print(f"  [Resume WARNING] Project checkpoint corrupted, re-initializing: {e}")
                project_state = {"story": story, "completed_scenes": []}

        scene_mp4_paths = []
        total_scenes = len(story["scenes"])
        transitions = plan_transitions(story["scenes"])

        # 2. Sequential Scene Production (Conserves RAM: ~120MB per scene)
        for i, scene in enumerate(story["scenes"], 1):
            scene_num = scene["scene_num"]
            scene_mp4 = episode_work_dir / f"scene_{scene_num:03d}.mp4"

            # Checkpoint resume check with integrity verification
            if scene_mp4.exists() and scene_num in project_state.get("completed_scenes", []):
                if self._verify_scene_mp4(scene_mp4):
                    print(f"  [Scene {scene_num}/{total_scenes}] Verified valid MP4 ({scene_mp4.stat().st_size // 1024} KB). Skipping (Resume Checkpoint).")
                    scene_mp4_paths.append(scene_mp4)
                    continue
                else:
                    print(f"  [Scene {scene_num}/{total_scenes}] Checkpoint file corrupted or incomplete (<10KB / unreadable). Discarding and re-rendering...")
                    scene_mp4.unlink(missing_ok=True)
                    if scene_num in project_state.get("completed_scenes", []):
                        project_state["completed_scenes"].remove(scene_num)

            print(f"  [Scene {scene_num}/{total_scenes}] Speaker: {scene['speaker']} | Line: \"{scene['dialogue']}\"")

            # Step 2a: Generate TTS
            audio_info = self.tts.generate_dialogue(
                text=scene["dialogue"],
                speaker=scene["speaker"],
                tag=f"{story_id}_s{scene_num}"
            )

            # Step 2b: Render Scene
            fade_in, fade_out = transitions[i - 1] if i - 1 < len(transitions) else (0.0, 0.0)
            self.renderer.render_scene(
                # The renderer seeds eye/gaze animation from story_id + scene number, so
                # pass it explicitly instead of letting it guess from a directory name.
                scene_data=dict(scene, story_id=story_id, fade_in=fade_in,
                                fade_out=fade_out),
                audio_data=audio_info,
                output_mp4=scene_mp4,
                sfx_delay_ms=350
            )

            # Post-render validation
            if not self._verify_scene_mp4(scene_mp4):
                raise RuntimeError(f"Scene {scene_num} failed rendering validation: {scene_mp4}")

            scene_mp4_paths.append(scene_mp4)
            if scene_num not in project_state["completed_scenes"]:
                project_state["completed_scenes"].append(scene_num)
                with open(project_file, "w", encoding="utf-8") as pf:
                    json.dump(project_state, pf, ensure_ascii=False, indent=2)

        # 3. Concatenate all scenes into final 30-second episode MP4
        concat_list_file = episode_work_dir / "concat_list.txt"
        with open(concat_list_file, "w", encoding="utf-8") as f:
            for p in scene_mp4_paths:
                f.write(f"file '{p.resolve().as_posix()}'\n")

        final_episode_path = EPISODES_DIR / f"{story_id}_final.mp4"
        print(f"\n[Pipeline] Concatenating {len(scene_mp4_paths)} scenes into {final_episode_path}...")

        concat_cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list_file),
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            str(final_episode_path)
        ]
        res = subprocess.run(concat_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"FFmpeg concatenation failed: {res.stderr}")

        # Post-concatenation verification
        if not final_episode_path.exists() or final_episode_path.stat().st_size < 50000:
            raise RuntimeError(f"Concatenated episode is missing or too small: {final_episode_path}")

        # Get final duration
        dur_cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(final_episode_path)
        ]
        dur_res = subprocess.run(dur_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        final_duration = float(dur_res.stdout.strip())

        print(f"[Pipeline] Episode Complete! Duration: {final_duration:.2f}s | Path: {final_episode_path}")

        return {
            "story_id": story_id,
            "title": title,
            "hook": story["hook"],
            "video_path": str(final_episode_path),
            "duration": final_duration,
            "total_scenes": total_scenes,
            "project_file": str(project_file)
        }


if __name__ == "__main__":
    pipeline = EpisodePipeline()
    result = pipeline.produce_episode()
    print("\nProduction Result:", result)
