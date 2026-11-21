"""Scene Renderer for Autonomous Hindi Animation Studio.
Renders 1080x1920 30fps frames with PyCairo vector graphics, multi-layer parallax,
skeletal rigged characters (Chiku & Gappu), animated lipsync, cartoon effects,
and mixes dialogue audio, sound effects, and background music with FFmpeg.
"""

import json
import math
import os
import subprocess
import zlib
from pathlib import Path
from typing import Dict, Any, Optional
import cairo

from studio.config import VIDEO_WIDTH, VIDEO_HEIGHT, FPS, INTERMEDIATE_DIR
from studio.audio.loudness import normalize_file
from studio.characters.chiku import ChikuRig
from studio.characters.gappu import GappuRig
from studio.characters.gaze import (
    ANCHOR_CAMERA,
    FaceController,
    expression_for_pose,
    gaze_toward,
)
from studio.characters.lipsync import VisemeTrack
from studio.characters.locomotion import MotionController, motions_for
from studio.characters.interaction import (
    InteractionDirector,
    plan_interaction,
    replace_body_hip,
)
from studio.characters.performance import (
    PerformanceFace,
    PerformancePlan,
    PerformanceTrack,
    plan_performance,
)
from studio.characters.visemes import VisemeTimeline
from studio.animation.background import BackgroundRenderer
from studio.animation.camera import Camera, CameraDirector
# How much clear air a held prop needs above the caption band before the frame lifts for it.
PROP_BAND_CLEARANCE = 10.0

from studio.characters.props import (
    PROPS,
    PropTrack,
    draw_prop,
    hand_point,
    prop_box,
    raise_arm_for_clearance,
)
from studio.animation.framing import (
    FramingReport,
    opaque_rect,
    overlap_area,
    plan_shot,
    screen_box,
    fits,
    subject_from_schema,
    world_y_for_screen,
)
from studio.animation.silhouette import subject_from_rig
from studio.animation.transitions import ffmpeg_fade_filters
from studio.animation.effects import (
    draw_sparkle, draw_dust_puff, draw_exclamation_pop, draw_vignette,
)
from studio.audio.sfx_library import SFXLibrary


# Stage (T41): the cast's placement, ground and eye line now come from a `Stage` rather than from
# four constants, so the same animation engine stages a 9:16 and a 16:9 scene. The portrait stage
# carries these exact values, which is why the portrait goldens still reproduce byte-for-byte.
from studio.animation.stage import Stage, stage_for


def _seed_for(*parts) -> int:
    """Stable seed so a re-render of the same scene animates identically."""

    return zlib.crc32(":".join(str(part) for part in parts).encode("utf-8"))


def _gaze_beats(own_x: float, partner_x: float, span: float,
                speaking: bool, facing: float = 1.0, eye_y: float = 1180.0) -> list:
    """Alternate eye contact with looks away, so nobody stares unblinkingly.

    A speaker looks at their partner more than a listener does, but both keep returning
    to the other character: that is what reads as a conversation instead of two solos.
    """

    screen_x, screen_y = gaze_toward(own_x, partner_x, eye_y, eye_y)
    # Rigs draw with scale * facing, so screen-space gaze is mirrored for a left-facing
    # character: convert to the rig's local axis before handing it to the pupil offset.
    partner = (screen_x * facing, screen_y)
    away = (-partner[0] * 0.55, partner[1] - 0.3) if speaking else ANCHOR_CAMERA
    events: list = []
    period = 2.1 if speaking else 2.8
    index = 0
    at = 0.0
    while at < span:
        events.append((at, partner if index % 2 == 0 else away))
        at += period
        index += 1
    return events


def _expression_schedule(scene_data, character: str, pose: str,
                         speaking: bool) -> list:
    """Build the expression timeline for one character in one scene."""

    posed = expression_for_pose(pose)
    if speaking:
        base = scene_data.get(f"{character}_expression") or posed
    else:
        # A listener keeps whatever their pose says, unless the pose is plain neutral, in
        # which case they get the attentive listening face.
        base = (scene_data.get(f"{character}_listening_expression")
                or (posed if posed != "neutral" else "listening"))
    schedule = [(0.0, base)]
    for change in scene_data.get(f"{character}_expressions") or []:
        try:
            at = float(change["at"])
            name = str(change["name"])
        except (KeyError, TypeError, ValueError):
            continue
        schedule.append((max(0.0, at), name))
    return schedule


class SceneRenderer:
    """Renders a single animated scene into a high-quality vertical MP4."""

    def __init__(self, width: int = VIDEO_WIDTH, height: int = VIDEO_HEIGHT, fps: int = FPS,
                 stage: Optional[Stage] = None, environment: Any = None,
                 foreground: Any = None):
        self.width = width
        self.height = height
        self.fps = fps
        self.stage = stage or stage_for(width, height)
        # Environment (T41): the aspect-specific part of a scene. A landscape scene plugs in a 16:9
        # environment that also casts shadows and supplies a foreground layer; a portrait scene
        # keeps the vertical backgrounds and has neither. Everything between them - rigs, faces,
        # gaze, lipsync, motion, interaction, props, camera - is shared, which is the point.
        self.bg_renderer = BackgroundRenderer(width, height)
        self.environment = environment or self.bg_renderer
        self.foreground = foreground
        self.sfx_lib = SFXLibrary()

    def render_scene(self, scene_data: Dict[str, Any], audio_data: Dict[str, Any],
                     output_mp4: Path, sfx_delay_ms: int = 400) -> Path:
        """Renders frames, mixes audio, and produces scene MP4."""
        duration = audio_data["duration"]
        # Add slight 0.5s pause at the end for natural pacing
        total_duration = duration + 0.5
        total_frames = max(int(total_duration * self.fps), 15)

        scene_num = scene_data.get("scene_num", 1)
        story_id = str(scene_data.get("story_id") or audio_data.get("story_id")
                       or Path(output_mp4).parent.name)
        speaker = scene_data.get("speaker", "narrator")
        dialogue = scene_data.get("dialogue", "")
        chiku_pose = scene_data.get("chiku_pose", "idle")
        gappu_pose = scene_data.get("gappu_pose", "idle")
        camera_style = scene_data.get("camera", "medium_pan")
        sfx_name = scene_data.get("sfx", "whoosh")
        bg_name = scene_data.get("bg", "jungle_clearing")

        # Camera direction (T35): a style is a short deterministic move, not a static zoom.
        stage = self.stage
        camera = Camera(self.width, self.height)
        director = CameraDirector(camera_style, total_duration, (self.width, self.height),
                                  face_y=stage.eye_y, zoom_range=stage.zoom_range)

        # Initialize Character Rigs
        # Chiku stands on left, Gappu on right
        chiku = ChikuRig(**stage.anchor("chiku"))
        chiku.facing = stage.facing("chiku")  # looking at the partner
        gappu = GappuRig(**stage.anchor("gappu"))
        gappu.facing = -1.0  # looking left

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, self.width, self.height)
        cr = cairo.Context(surface)

        subtitle_surface = None
        subtitle_path = scene_data.get("subtitle_png")
        if subtitle_path:
            try:
                subtitle_surface = cairo.ImageSurface.create_from_png(str(subtitle_path))
            except Exception as exc:
                print(f"[Render] WARNING: could not load subtitle overlay {subtitle_path}: {exc}")

        band_rect = None
        if subtitle_surface is not None:
            try:
                band_rect = opaque_rect(subtitle_surface)
            except Exception as exc:
                print(f"[Render] WARNING: could not measure the caption band: {exc}")

        title_surface = None
        title_path = scene_data.get("title_png")
        if title_path:
            try:
                title_surface = cairo.ImageSurface.create_from_png(str(title_path))
            except Exception as exc:
                print(f"[Render] WARNING: could not load title overlay {title_path}: {exc}")

        # Face controllers (T32): gaze, saccades, blinks and expressions per character.
        chiku_face = FaceController(
            chiku.schema,
            seed=_seed_for(story_id, scene_num, "chiku"),
            span=total_duration + 2.0,
            schedule=_expression_schedule(scene_data, "chiku", chiku_pose,
                                          speaker == "chiku"),
            scripted_gaze=_gaze_beats(stage.slot("chiku").x, stage.slot("gappu").x,
                                      total_duration,
                                      speaking=speaker == "chiku",
                                      facing=chiku.facing, eye_y=stage.eye_y),
        )
        gappu_face = FaceController(
            gappu.schema,
            seed=_seed_for(story_id, scene_num, "gappu"),
            span=total_duration + 2.0,
            schedule=_expression_schedule(scene_data, "gappu", gappu_pose,
                                          speaker == "gappu"),
            scripted_gaze=_gaze_beats(stage.slot("gappu").x, stage.slot("chiku").x,
                                      total_duration,
                                      speaking=speaker == "gappu",
                                      facing=gappu.facing, eye_y=stage.eye_y),
        )
        # Interaction layer (T35b): keeps the two bodies apart, turns them toward each
        # other, and lets a speaker's emphasis reach the listener. With the plan empty and
        # the anchors already apart this resolves to the identity transform, so existing
        # episodes render unchanged. FACTORY_NO_INTERACTION=1 removes it entirely.
        interaction = InteractionDirector(
            anchor_a=chiku.schema.anchor["x"], anchor_b=gappu.schema.anchor["x"],
            plan=(None if os.environ.get("FACTORY_NO_INTERACTION")
                  else plan_interaction(dialogue, duration=total_duration, speaker=speaker,
                                        listener=("gappu" if speaker == "chiku" else "chiku"),
                                        seed=_seed_for(story_id, scene_num, "interaction"))),
            facing_a=int(math.copysign(1, chiku.facing)),
            facing_b=int(math.copysign(1, gappu.facing)),
        )

        # Shot planning (T39): the camera is told what has to be on screen. The subjects come
        # from the character schemas - the same source the rigs use - so the framing can never
        # disagree with the drawing. A character that gestures must be fully in frame, so the
        # scripted style is treated as a request and widened when it would crop one.
        # Subject boxes are measured from the rigs, not predicted from the schema (T41): the old
        # formula put Chiku at 278 units tall against 335 drawn, and read the anchor out of the
        # character file, so a restaged character was framed where its file said it lived rather
        # than where the stage put it.
        subjects = {
            "chiku": subject_from_rig(chiku, chiku_pose),
            "gappu": subject_from_rig(gappu, gappu_pose),
        }
        # The planner applies each kind's own semantics: a close-up must belong to the character
        # who is performing, and a relational shot (medium/two_shot/wide) must hold the whole
        # cast. `must_show` is only for a caller that insists on particular characters.
        must_show = None
        # A hand-off or any scene that is about the pair rather than one of them asks for both
        # characters on screen; pair lock is the blunt version of that, and also a switch for
        # A/B renders while the shot policy is being decided by eye.
        if (os.environ.get("FACTORY_CAMERA_PAIR_LOCK") == "1"
                or str(scene_data.get("interaction", "")) in ("contact", "hand_off")):
            must_show = ["chiku", "gappu"]
        # Props (T40): an object the scene is about, held in a real hand. Opt-in through scene
        # data, so an episode without a prop renders exactly as it did before.
        prop_name = scene_data.get("prop")
        prop_track = None
        if prop_name:
            spec = PROPS.get(str(prop_name))
            if spec is None:
                print(f"[Render] WARNING: unknown prop {prop_name!r}; skipping")
            else:
                holder = str(scene_data.get("prop_holder") or
                             (speaker if speaker in subjects else "chiku"))
                if holder not in subjects:
                    holder = next(iter(subjects))
                handoff_to = scene_data.get("prop_handoff_to")
                if handoff_to and handoff_to not in subjects:
                    handoff_to = None
                handoff_at = scene_data.get("prop_handoff_at")
                if handoff_at is not None:
                    handoff_at = float(handoff_at)
                    if handoff_at <= 1.0:  # a fraction of the scene is easier to author
                        handoff_at = handoff_at * total_duration
                prop_track = PropTrack(
                    spec, holder=holder, side=str(scene_data.get("prop_side", "right")),
                    handoff_to=str(handoff_to) if handoff_to else None,
                    handoff_side=str(scene_data.get("prop_handoff_side", "left")),
                    handoff_at=handoff_at,
                    handoff_duration=float(scene_data.get("prop_handoff_duration", 0.45)))

        # The prop is part of what the camera has to frame, so the shot is planned with its
        # box included. Computed at the holder's *resting* hand so the plan is stable.
        prop_probe = None
        if prop_track is not None:
            probe_hands = {
                "chiku": hand_point(chiku, prop_track.hand_for("chiku")),
                "gappu": hand_point(gappu, prop_track.hand_for("gappu")),
            }
            prop_probe = prop_track.box_at(0.0, probe_hands)

        shot = plan_shot(camera_style, subjects, (self.width, self.height),
                         extras=[prop_probe] if prop_probe else [],
                         speaker=speaker if speaker in subjects else None,
                         must_show=must_show, zoom_range=stage.zoom_range,
                         kind_zoom=stage.kind_zoom())
        if os.environ.get("FACTORY_CAMERA_FRAMING", "1") == "1":
            director.shot = shot
        if shot.escalated:
            print(f"[Render] Scene {scene_num}: camera {camera_style} -> {shot.kind} "
                  f"({shot.reason}) to keep {', '.join(shot.subjects)} in frame")
        framing = FramingReport(
            (self.width, self.height),
            required=tuple(shot.subjects) + (("prop",) if prop_track is not None else ()))
        # Subtitle collision (T41): a character standing behind the caption band is unreadable and
        # the caption is unreadable too. Measured per frame from the same boxes the framing
        # report uses, against the band rectangle taken from the overlay's own alpha.
        band_collision_frames = 0
        prop_occluded_frames = 0
        prop_worst_overlap = 0.0
        prop_lifted_frames = 0
        framing_gesture_frames = 0

        # Locomotion layer (T33). Scenes without a motion keep the pose exactly as it was,
        # so every existing episode renders unchanged.
        chiku_motion = MotionController(
            motions_for(scene_data, "chiku")[0], duration=total_duration,
            seed=_seed_for(story_id, scene_num, "chiku", "motion"), facing=chiku.facing)
        gappu_motion = MotionController(
            motions_for(scene_data, "gappu")[0], duration=total_duration,
            seed=_seed_for(story_id, scene_num, "gappu", "motion"), facing=gappu.facing)

        # Performance layer (T34): reaction beats derived from the spoken line, so the
        # listener nods and recoils instead of standing in an authored pose for the whole
        # scene. An empty plan leaves every frame exactly as it was.
        # FACTORY_NO_PERFORMANCE=1 disables the layer, which is how the A/B render that
        # proves this layer only adds motion is produced, and the switch to pull if the
        # beats ever look wrong in a real episode.
        if os.environ.get("FACTORY_NO_PERFORMANCE"):
            plan = PerformancePlan()
        else:
            plan = plan_performance(dialogue, duration=total_duration, speaker=speaker,
                                    seed=_seed_for(story_id, scene_num, "performance"))
        chiku_perf = PerformanceTrack(plan.for_character("chiku"), total_duration)
        gappu_perf = PerformanceTrack(plan.for_character("gappu"), total_duration)
        if plan.chiku or plan.gappu:
            print(f"[Render] Scene {scene_num}: performance beats "
                  f"chiku={len(plan.chiku)} gappu={len(plan.gappu)}")

        chiku.attach_face(PerformanceFace(chiku_face, chiku_perf))
        gappu.attach_face(PerformanceFace(gappu_face, gappu_perf))

        # Mix the audio bed first so the video encoder can mux it directly.
        sfx_path = self.sfx_lib.get_sfx(sfx_name)
        bgm_path = self.sfx_lib.get_bgm()
        voice_path = Path(audio_data["audio_path"])
        lipsync_track = VisemeTrack.from_audio(voice_path, fps=self.fps)
        dialogue_text = str(audio_data.get("text") or scene_data.get("dialogue") or "")
        viseme_timeline = VisemeTimeline.from_text(
            dialogue_text,
            duration=duration,
            fps=self.fps,
            boundaries=audio_data.get("boundaries"),
            envelope=lipsync_track if len(lipsync_track) else None,
        )
        mixed_audio = INTERMEDIATE_DIR / f"scene_{scene_num:03d}_mixed.wav"
        filter_complex = (
            f"[0:a]volume=1.0[v];"
            f"[1:a]adelay={sfx_delay_ms}|{sfx_delay_ms},volume=0.75[s];"
            f"[2:a]volume=0.16[m];"
            f"[v][s][m]amix=inputs=3:duration=first:dropout_transition=2[aout]"
        )
        audio_cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(voice_path),
            "-i",
            str(sfx_path),
            "-i",
            str(bgm_path),
            "-filter_complex",
            filter_complex,
            "-map",
            "[aout]",
            "-ac",
            "2",
            "-ar",
            "44100",
            str(mixed_audio),
        ]
        audio_result = subprocess.run(
            audio_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        if audio_result.returncode != 0:
            raise RuntimeError(f"Scene {scene_num} audio mix failed: {audio_result.stderr[-2000:]}")

        # EBU R128 normalisation (T36). The animated path used to ship at about -24 LUFS,
        # ten LU below reference; a linear gain fixes the level without touching duration,
        # so A/V sync and lip-sync stay exact. A file that cannot be measured is reported
        # rather than silently replaced.
        loudness = normalize_file(mixed_audio, keep_duration=total_duration)
        measured = loudness.get("after") or {}
        if loudness.get("applied"):
            print(f"[Render] Scene {scene_num}: loudness "
                  f"{(loudness.get('before') or {}).get('integrated_lufs', float('nan')):.1f} -> "
                  f"{measured.get('integrated_lufs', float('nan')):.1f} LUFS "
                  f"(peak {measured.get('true_peak_dbtp', float('nan')):.1f} dBTP, "
                  f"delta {loudness.get('duration_delta')}s)")
        else:
            print(f"[Render] Scene {scene_num}: WARNING loudness not applied: "
                  f"{loudness.get('error', 'unknown')}")

        output_mp4.parent.mkdir(parents=True, exist_ok=True)
        print(f"[Render] Scene {scene_num}: Rendering {total_frames} frames ({total_duration:.2f}s)...")
        # Scene transitions (T37): a location change dips to black, a beat in the same
        # location cuts directly. Time-based, so it never touches the frame loop.
        fade_filters = ffmpeg_fade_filters(
            float(scene_data.get("fade_in") or 0.0),
            float(scene_data.get("fade_out") or 0.0),
            total_duration,
        )
        if fade_filters:
            print(f"[Render] Scene {scene_num}: transitions {'; '.join(fade_filters)}")
        encode_cmd = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-nostats",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgra",
            "-s",
            f"{self.width}x{self.height}",
            "-r",
            str(self.fps),
            "-i",
            "-",
            "-i",
            str(mixed_audio),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
            *(["-vf", ",".join(fade_filters)] if fade_filters else []),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output_mp4),
        ]
        encoder = subprocess.Popen(
            encode_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if encoder.stdin is None:
            raise RuntimeError("could not open ffmpeg stdin")
        try:
            for frame_idx in range(total_frames):
                t = frame_idx / float(self.fps)
                is_dialogue_playing = t <= duration
                chiku_talking = is_dialogue_playing and (speaker == "chiku")
                gappu_talking = is_dialogue_playing and (speaker == "gappu")

                # Interaction resolves the two bodies together, so it has to run after both
                # motions are known and before either rig is posed - and before the camera,
                # which now frames the characters where they actually are this frame.
                chiku_body = chiku_perf.accent_at(t).on_body(chiku_motion.state_at(t))
                gappu_body = gappu_perf.accent_at(t).on_body(gappu_motion.state_at(t))
                hip_a, hip_b = interaction.resolve(chiku_body.hip_x, gappu_body.hip_x)
                chiku_body = replace_body_hip(chiku_body, hip_a)
                gappu_body = replace_body_hip(gappu_body, hip_b)
                layer_a, layer_b = interaction.bodies(t, hip_a, hip_b, speaker)
                if layer_a is not None:
                    chiku_body = chiku_body.merged_with(layer_a)
                if layer_b is not None:
                    gappu_body = gappu_body.merged_with(layer_b)

                # Poses first: hands, and therefore props, depend on them. Reading a hand
                # before the pose is updated would place the prop using last frame's arm.
                chiku.update_pose(
                    chiku_pose, t, is_talking=chiku_talking, phoneme_intensity=0.8,
                    lipsync=lipsync_track, timeline=viseme_timeline,
                    body=chiku_body)
                gappu.update_pose(
                    gappu_pose, t, is_talking=gappu_talking, phoneme_intensity=0.7,
                    lipsync=lipsync_track, timeline=viseme_timeline,
                    body=gappu_body)
                chiku.face_state_at(t)
                gappu.face_state_at(t)

                camera_frame = director.state_at(
                    t, positions={"chiku": chiku.x + hip_a, "gappu": gappu.x + hip_b})
                camera.zoom = camera_frame.zoom
                camera.pan_x = camera_frame.pan_x
                camera.pan_y = camera_frame.pan_y
                reach_a = interaction.amount_at(t, 0)
                reach_b = interaction.amount_at(t, 1)
                if reach_a > 0.0 or reach_b > 0.0:
                    framing_gesture_frames += 1

                # Props (T40): where the prop is, whether the caption band will cover it, and
                # if so how far the frame has to lift to keep the story object visible.
                prop_point = None
                if prop_track is not None:
                    for who, rig in (("chiku", chiku), ("gappu", gappu)):
                        if prop_track.held_by(t) not in (who, None):
                            continue
                        arm = prop_track.hand_for(who)
                        band_top = (world_y_for_screen(band_rect[1], camera.zoom, camera.pan_y,
                                                       (self.width, self.height))
                                    if band_rect is not None else None)
                        delta = raise_arm_for_clearance(rig, arm, prop_track.spec, band_top)
                        if delta:
                            if arm == "left":
                                rig.arm_l_angle += delta
                            else:
                                rig.arm_r_angle += delta
                    hands = {"chiku": hand_point(chiku, prop_track.hand_for("chiku")),
                             "gappu": hand_point(gappu, prop_track.hand_for("gappu"))}
                    prop_point = prop_track.point_at(t, hands)
                    if band_rect is not None:
                        prop_screen = screen_box(prop_box(prop_point, prop_track.spec),
                                                 camera.zoom, camera.pan_x, camera.pan_y,
                                                 (self.width, self.height))
                        shortfall = (prop_screen[3] + PROP_BAND_CLEARANCE) - band_rect[1]
                        if shortfall > 0.0:
                            # Lift the frame, but never at the cost of cropping a character:
                            # the characters are the shot, the band is a constraint.
                            lifted = camera.pan_y + shortfall / camera.zoom
                            if all(fits(live_subjects[name].bounds(1.0), camera.zoom,
                                        camera.pan_x, lifted, (self.width, self.height))
                                   for name in shot.subjects):
                                prop_lift = shortfall / camera.zoom
                                camera.pan_y = lifted
                                prop_lifted_frames += 1
                # Measured on the frame that will actually be drawn, after any lift.
                if prop_point is not None and band_rect is not None:
                    prop_screen = screen_box(prop_box(prop_point, prop_track.spec),
                                             camera.zoom, camera.pan_x, camera.pan_y,
                                             (self.width, self.height))
                    shared = overlap_area(prop_screen, band_rect)
                    if shared > 0.0:
                        prop_occluded_frames += 1
                        prop_worst_overlap = max(prop_worst_overlap, shared)
                extra_boxes = ({"prop": prop_box(prop_point, prop_track.spec)}
                               if prop_point else None)
                # Per-frame subjects: a jumping or gesturing character is not where the idle
                # silhouette was, and the report exists to catch exactly that.
                live_subjects = {
                    "chiku": subject_from_rig(chiku, chiku_pose, chiku_body),
                    "gappu": subject_from_rig(gappu, gappu_pose, gappu_body),
                }
                if band_rect is not None:
                    for name in shot.subjects:
                        if name not in live_subjects:
                            continue
                        # The *drawn* extent, without the framing safety padding: a padded box
                        # crosses the caption band on every frame (which is what the first
                        # version reported) while the character itself does not.
                        rig = chiku if name == "chiku" else gappu
                        pose = chiku_pose if name == "chiku" else gappu_pose
                        body = chiku_body if name == "chiku" else gappu_body
                        drawn = subject_from_rig(rig, pose, body, pad=0.0, reach=0.0)
                        box = drawn.bounds(0.0)
                        # The face, not the whole body: a close-up legitimately has the character's
                        # torso behind the caption band, but a face behind it is unreadable. The
                        # first version measured the whole silhouette and reported every frame of
                        # every scene, which is a measurement of the wrong thing.
                        head_height = (box[3] - box[1]) * 0.38
                        box = (box[0], box[1], box[2], box[1] + head_height)
                        if overlap_area(screen_box(box, camera.zoom, camera.pan_x,
                                                   camera.pan_y, (self.width, self.height)),
                                        band_rect) > 0.0:
                            band_collision_frames += 1
                            break

                framing.add(t, camera.zoom, camera.pan_x, camera.pan_y, live_subjects,
                            reach={"chiku": reach_a, "gappu": reach_b},
                            extras=extra_boxes)
                if camera_style == "action_shake" and 0.3 < t < 1.2:
                    camera.trigger_shake(0.2)
                camera.update(1.0 / self.fps)

                cr.save()
                cr.set_operator(cairo.OPERATOR_CLEAR)
                cr.paint()
                cr.restore()

                self.environment.render_by_name(
                    bg_name, cr, t, camera.pan_x, camera.pan_y,
                    zoom=(camera.zoom if os.environ.get("FACTORY_CAMERA_ZOOM_BG", "1") == "1"
                          else 1.0))

                cr.save()
                camera.apply(cr, t)
                # Contact shadows (T41): only an environment with a floor can take them, and they
                # are drawn under the cast so a character stands on the ground instead of floating
                # over it.
                shadow = getattr(self.environment, "draw_character_shadow", None)
                if shadow is not None:
                    shadow(cr, chiku.x + hip_a, stage.ground_y,
                           subject_from_rig(chiku, chiku_pose).half_w, 1.0)
                    shadow(cr, gappu.x + hip_b, stage.ground_y,
                           subject_from_rig(gappu, gappu_pose).half_w, 0.9)
                face_a, face_b = interaction.facing(hip_a, hip_b)
                if face_a != int(math.copysign(1, chiku.facing)):
                    chiku.facing = float(face_a)
                if face_b != int(math.copysign(1, gappu.facing)):
                    gappu.facing = float(face_b)

                # Props are drawn in the same world space as the rigs, after them, so a held
                # object sits on top of the hand that holds it.
                if prop_track is not None and prop_point is not None:
                    draw_prop(cr, prop_track.spec.name, prop_point,
                              angle=prop_track.angle_at(t))

                if sfx_name == "twinkle" or "\u092a\u0924\u094d\u0925\u0930" in dialogue:
                    sparkle_rot = t * 2.5
                    spark_x, spark_y = stage.at("chiku", 80.0, -300.0)
                    draw_sparkle(
                        cr,
                        spark_x + math.sin(t * 3) * 15,
                        spark_y + math.cos(t * 3) * 15,
                        32 + math.sin(t * 6) * 8,
                        sparkle_rot,
                    )
                    draw_sparkle(
                        cr,
                        spark_x + 60.0,
                        spark_y - 50.0,
                        20 + math.cos(t * 5) * 6,
                        -sparkle_rot * 1.2,
                    )

                if chiku_pose == "excited_jump" and (t % 0.78 < 0.25):
                    dust_x, dust_y = stage.at("chiku", 0.0, 10.0)
                    draw_dust_puff(cr, dust_x, dust_y, progress=(t % 0.78) / 0.25, scale=1.2)

                if chiku_pose == "shocked_freeze" and t < 1.2:
                    bang_x, bang_y = stage.at("chiku", 0.0, -430.0)
                    draw_exclamation_pop(cr, bang_x, bang_y, progress=min(1.0, t / 0.8))

                # A close-up frames one character: drawing the other would leave a sliver
                # of them at the frame edge, which reads as a mistake rather than a shot.
                if director.subject != "gappu":
                    chiku.draw(cr)
                if director.subject != "chiku":
                    gappu.draw(cr)
                cr.restore()

                # Foreground (T41): drawn after the cast so the near foliage overlaps them. This
                # is what makes a character read as standing inside the scene rather than on top
                # of a backdrop.
                if self.foreground is not None:
                    self.foreground.render_by_name(
                        bg_name, cr, t, camera.pan_x, camera.pan_y,
                        zoom=(camera.zoom if os.environ.get("FACTORY_CAMERA_ZOOM_BG", "1") == "1"
                              else 1.0))

                # Lens vignette (T35): screen space, above the scene and below the
                # subtitle band so captions keep full contrast.
                draw_vignette(cr, self.width, self.height)

                if title_surface is not None and t < 2.8:
                    alpha = min(1.0, max(0.0, (2.8 - t) / 0.6))
                    cr.set_source_surface(title_surface, 0, 0)
                    cr.paint_with_alpha(alpha)

                if subtitle_surface is not None and is_dialogue_playing:
                    cr.set_source_surface(subtitle_surface, 0, 0)
                    cr.paint()

                surface.flush()
                stride = surface.get_stride()
                row_bytes = self.width * 4
                if stride == row_bytes:
                    payload = bytes(surface.get_data())
                else:
                    raw = surface.get_data()
                    payload = b"".join(
                        raw[row * stride : row * stride + row_bytes]
                        for row in range(self.height)
                    )
                encoder.stdin.write(payload)

            encoder.stdin.close()
            stderr = encoder.stderr.read().decode("utf-8", errors="replace") if encoder.stderr else ""
            return_code = encoder.wait(timeout=120)
            if return_code != 0:
                raise RuntimeError(f"Scene {scene_num} encode failed: {stderr[-2000:]}")
        except Exception as exc:
            encoder.kill()
            err = ""
            if encoder.stderr is not None:
                err = encoder.stderr.read().decode("utf-8", errors="replace")
            # Include the exception: an empty ffmpeg stderr used to hide a Python bug in the
            # frame loop behind "video pipe failed", which told a reader nothing.
            raise RuntimeError(
                f"Scene {scene_num} video pipe failed: {type(exc).__name__}: {exc} "
                f"| ffmpeg: {err[-1500:]}") from exc

        # Framing report (T39): what the camera actually covered, frame by frame, measured with
        # the same projection the renderer used. Written next to the scene so QC can gate on it
        # and a human can see which subject was cropped and by how much.
        summary = framing.summary()
        summary.update({
            "scene": scene_num,
            "camera_style": camera_style,
            "shot": shot.kind,
            "shot_subjects": list(shot.subjects),
            "shot_zoom": round(shot.zoom, 4),
            "escalated": shot.escalated,
            "reason": shot.reason,
            "gesture_frames": framing_gesture_frames,
            "subtitle_collision_frames": band_collision_frames,
            "occlusion": ({"prop": {"frames": prop_occluded_frames,
                                    "lifted_frames": prop_lifted_frames,
                                    "worst_overlap_px": round(prop_worst_overlap, 1),
                                    "band": [round(value, 1) for value in band_rect]}}
                          if prop_track is not None and band_rect is not None else {}),
        })
        try:
            report_path = Path(output_mp4).with_name(Path(output_mp4).stem + "_framing.json")
            report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
            cropped = {name: data["cropped_frames"]
                       for name, data in summary["subjects"].items()
                       if data["cropped_frames"]}
            print(f"[Render] Scene {scene_num} framing: shot={shot.kind} "
                  f"zoom={shot.zoom:.2f} "
                  + (f"CROPPED {cropped}" if cropped else "all subjects in frame"))
        except Exception as exc:  # a report must never fail a render
            print(f"[Render] WARNING: could not write framing report: {exc}")

        print(f"[Render] Scene {scene_num} successfully encoded -> {output_mp4}")
        return output_mp4
