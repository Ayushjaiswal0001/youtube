"""Gappu (गप्पू) Character Rig - Reusable 2D Vector Animation.
The smart, observant little mouse with round spectacles.
"""

import math
from typing import Optional, Tuple
import cairo
from studio.characters.eyes import draw_brows, draw_eyes
from studio.characters.mouth import draw_mouth
from studio.characters.shapes import draw_shape
from studio.characters.schema import CharacterSchema, load_schema
from studio.characters.rig_base import (
    JointNode, Viseme, draw_ellipse, draw_capsule,
    ease_in_out_quad, ease_out_bounce
)

# Palette, proportions and timings are data: content/characters/gappu.json
GAPPU_SCHEMA: CharacterSchema = load_schema("gappu")

COLOR_FUR = GAPPU_SCHEMA.color("fur")
COLOR_FUR_LIGHT = GAPPU_SCHEMA.color("fur_light")
COLOR_EAR_INNER = GAPPU_SCHEMA.color("inner_ear")
COLOR_NOSE = GAPPU_SCHEMA.color("nose")
COLOR_BOWTIE = GAPPU_SCHEMA.color("bowtie")
COLOR_GLASSES = GAPPU_SCHEMA.color("glasses")
COLOR_GLASS_TINT = GAPPU_SCHEMA.color("glass_tint")
COLOR_EYE_WHITE = GAPPU_SCHEMA.color("eye_white")
COLOR_PUPIL = GAPPU_SCHEMA.color("pupil")
COLOR_TAIL = GAPPU_SCHEMA.color("tail")
COLOR_SHADOW = GAPPU_SCHEMA.color("shadow")
COLOR_OUTLINE = GAPPU_SCHEMA.color("outline")


class GappuRig:
    """Reusable 2D skeletal rig for Gappu the Mouse."""

    def __init__(self, x: float | None = None, y: float | None = None,
                 scale: float | None = None, schema: CharacterSchema | None = None):
        self.schema = schema or GAPPU_SCHEMA
        self.prop = self.schema.proportions
        self.timing = self.schema.timing
        self.x = self.schema.anchor["x"] if x is None else x
        self.y = self.schema.anchor["y"] if y is None else y
        self.scale = self.schema.anchor["scale"] if scale is None else scale
        self.facing = self.schema.anchor["facing"]  # -1.0 faces left toward Chiku

        # Joint Nodes (geometry from the character schema)
        self.root = JointNode("root", local_x=self.x, local_y=self.y)
        self.torso = JointNode("torso", parent=self.root, local_y=self.prop.torso_y)
        self.head = JointNode("head", parent=self.torso, local_y=self.prop.head_joint_y)

        # Facial & Gestural State
        self.blink_t = 0.0
        self.look_x = 0.0
        self.look_y = 0.0
        self.viseme = Viseme.SMILE
        self.mouth_open = 0.0
        # Set by FaceController (T32); None keeps the original eye rendering.
        self.eye_state = None
        self.eyebrow_tilt = 0.0
        self.eyebrow_y = 0.0
        self.glasses_slide = 0.0  # pushes glasses up nose

        # Limbs
        self.arm_l_angle = 0.1
        self.arm_r_angle = -0.1
        self.leg_l_angle = 0.0
        self.leg_r_angle = 0.0
        self.tail_wave = 0.0
        self.jump_y = 0.0
        self.hip_x = 0.0
        self.squash = 1.0

    @property
    def colors(self) -> dict:
        return {
            "eye_white": COLOR_EYE_WHITE,
            "pupil": COLOR_PUPIL,
            "outline": COLOR_OUTLINE,
            "lid": COLOR_FUR,
            "brow": COLOR_OUTLINE,
        }

    def attach_face(self, controller) -> None:
        """Drive eyes, gaze and brows from a FaceController while drawing."""

        self._face = controller

    def face_state_at(self, t: float):
        face = getattr(self, "_face", None)
        self.eye_state = face.state_at(t) if face is not None else None
        return self.eye_state

    def update_pose(self, pose: str, t: float, is_talking: bool = False, phoneme_intensity: float = 0.5,
                    lipsync: object | None = None, timeline: object | None = None,
                    body: object | None = None):
        """Update Gappu's joints based on time and pose."""
        # Breathing / sway / blink / tail come from the schema's timing profile
        self.torso.local_y = self.prop.torso_y + self.timing.breath(t)
        self.torso.local_rot = self.timing.sway(t)
        self.blink_t = self.timing.blink(t)
        self.tail_wave = self.timing.tail(t)

        # Reset everything a pose or a motion may write. Poses are not required to set all
        # of these, and without a reset a value from the previous frame survives -- which
        # turns "add the walk offset" into an integrator that walks the character off screen.
        self.jump_y = 0.0
        self.hip_x = 0.0
        self.squash = 1.0
        self.head.local_rot = 0.0
        self.leg_l_angle = 0.0
        self.leg_r_angle = 0.0
        self.arm_l_angle = 0.1
        self.arm_r_angle = -0.1
        self.eyebrow_y = 0.0
        self.eyebrow_tilt = 0.0

        # Talking mouth animation: narration envelope when available, sine fallback.
        if is_talking:
            if timeline is not None and len(timeline):  # type: ignore[arg-type]
                self.viseme = timeline.shape_at(t)  # type: ignore[union-attr]
                envelope = lipsync.at(t) if (lipsync is not None and len(lipsync)) else 1.0  # type: ignore[union-attr]
                if envelope <= 0.06:
                    self.viseme = Viseme.CLOSED
                    self.mouth_open = 0.0
                else:
                    self.mouth_open = timeline.scale_at(t) * (0.35 + 0.65 * envelope) * phoneme_intensity  # type: ignore[union-attr]
            elif lipsync is not None and len(lipsync):  # type: ignore[arg-type]
                self.mouth_open = lipsync.at(t) * phoneme_intensity  # type: ignore[union-attr]
                self.viseme = lipsync.viseme_at(t)  # type: ignore[union-attr]
            else:
                self.mouth_open = abs(math.sin(t * 14.0)) * phoneme_intensity
                if self.mouth_open > 0.6:
                    self.viseme = Viseme.OPEN_WIDE
                elif self.mouth_open > 0.3:
                    self.viseme = Viseme.OPEN_SMALL
                else:
                    self.viseme = Viseme.SMILE
        else:
            self.mouth_open = 0.0
            self.viseme = Viseme.SMILE

        # Pose specifics
        if pose == "idle" or pose == "observing":
            self.head.local_rot = math.sin(t * 1.5) * 0.04
            self.arm_l_angle = 0.2 + math.sin(t * 2.0) * 0.05
            self.arm_r_angle = -0.2 - math.sin(t * 2.0) * 0.05
            self.leg_l_angle = 0.0
            self.leg_r_angle = 0.0
            self.eyebrow_y = 0.0
            self.eyebrow_tilt = 0.0
            self.glasses_slide = 0.0

        elif pose == "skeptical_eyebrow":
            # One brow raised high, arms folded
            self.head.local_rot = -0.08
            self.arm_l_angle = 0.9   # folded arms
            self.arm_r_angle = -0.9
            self.eyebrow_y = -10.0
            self.eyebrow_tilt = -0.25
            self.glasses_slide = 2.0

        elif pose == "laughing_point":
            # Giggling with one hand pointing at Chiku
            self.head.local_rot = math.sin(t * 10.0) * 0.15
            self.arm_l_angle = -1.1  # pointing forward
            self.arm_r_angle = 0.6   # clutching tummy laughing
            self.eyebrow_y = -4.0
            self.eyebrow_tilt = 0.15
            self.jump_y = -abs(math.sin(t * 10.0)) * 12.0
            if not is_talking:
                self.viseme = Viseme.OPEN_WIDE

        elif pose == "satisfied_nod":
            self.head.local_rot = math.sin(t * 5.0) * 0.12  # nodding
            self.arm_l_angle = 0.3
            self.arm_r_angle = -0.3
            self.eyebrow_y = -2.0
            self.eyebrow_tilt = 0.1
            if not is_talking:
                self.viseme = Viseme.SMILE

        elif pose == "facepalm":
            self.head.local_rot = 0.18  # head hung down
            self.arm_l_angle = -1.5     # hand covering face
            self.arm_r_angle = 0.1
            self.eyebrow_y = 6.0
            self.eyebrow_tilt = -0.2

        elif pose == "hands_on_hips":
            self.head.local_rot = -0.05
            self.arm_l_angle = 0.8
            self.arm_r_angle = -0.8
            self.eyebrow_y = -4.0
            self.eyebrow_tilt = 0.1

        self.apply_body(body)

    def apply_body(self, body) -> None:
        """Apply a locomotion frame on top of the current pose.

        Pose and motion are separate layers: the pose owns attitude, the motion owns
        movement. Angles add, arms are replaced only when the motion actually moves them,
        and lip-sync / eyes are untouched.
        """

        if body is None:
            self.hip_x = 0.0
            self.squash = 1.0
            return
        self.hip_x = body.hip_x
        self.jump_y += body.jump_y
        self.torso.local_rot += body.lean
        self.leg_l_angle += body.leg_l
        self.leg_r_angle += body.leg_r
        self.head.local_rot += body.head_tilt
        if body.arm_l is not None:
            self.arm_l_angle = body.arm_l
        if body.arm_r is not None:
            self.arm_r_angle = body.arm_r
        self.arm_l_angle += body.arm_l_delta
        self.arm_r_angle += body.arm_r_delta
        self.squash = body.squash

    def draw(self, cr: cairo.Context):
        """Renders full 2D vector mouse to Cairo context."""
        cr.save()
        cr.translate(self.x + self.hip_x, self.y + self.jump_y)
        cr.scale(self.scale * self.facing, self.scale * self.squash)

        # 1. Shadow
        P = self.prop
        shadow_scale = max(0.5, 1.0 - abs(self.jump_y) / 80.0)
        draw_ellipse(cr, 0, 0, P.shadow_rx * shadow_scale, P.shadow_ry * shadow_scale,
                     fill_color=(COLOR_SHADOW[0], COLOR_SHADOW[1], COLOR_SHADOW[2],
                                 COLOR_SHADOW[3] * shadow_scale))

        # 2. Long Thin Mouse Tail (data: shapes.tail)
        draw_shape(cr, self.schema.shape("tail"), self.schema.palette, wave=self.tail_wave)

        # 3. Feet
        # Left Foot
        draw_ellipse(cr, -P.leg_attach_x, P.leg_attach_y, P.foot_rx, P.foot_ry,
                     fill_color=COLOR_EAR_INNER, stroke_color=COLOR_OUTLINE, stroke_width=3.5)
        # Right Foot
        draw_ellipse(cr, P.leg_attach_x, P.leg_attach_y, P.foot_rx, P.foot_ry,
                     fill_color=COLOR_EAR_INNER, stroke_color=COLOR_OUTLINE, stroke_width=3.5)

        # 4. Plump Pear-shaped Torso
        cr.save()
        cr.translate(0, self.torso.local_y + P.torso_draw_offset)
        cr.rotate(self.torso.local_rot)

        # Body base
        draw_ellipse(cr, 0, 0, P.torso_rx, P.torso_ry, fill_color=COLOR_FUR, stroke_color=COLOR_OUTLINE, stroke_width=4)

        # Light tummy patch
        draw_ellipse(cr, 0, P.muzzle_y, P.muzzle_rx, P.muzzle_ry, fill_color=COLOR_FUR_LIGHT)

        # Cute Lime-Green Bowtie (data: shapes.bowtie + shapes.bowtie_knot)
        draw_shape(cr, self.schema.shape("bowtie"), self.schema.palette)
        draw_shape(cr, self.schema.shape("bowtie_knot"), self.schema.palette)

        # 5. Arms
        # Left Arm
        cr.save()
        cr.translate(-P.arm_attach_x, P.arm_attach_y)
        cr.rotate(self.arm_l_angle)
        draw_capsule(cr, 0, 0, -P.arm_shift, P.arm_len, P.arm_r, fill_color=COLOR_FUR, stroke_color=COLOR_OUTLINE, stroke_width=3.5)
        draw_ellipse(cr, -P.arm_shift, P.arm_len + 5, P.hand_rx, P.hand_ry, fill_color=COLOR_EAR_INNER, stroke_color=COLOR_OUTLINE, stroke_width=3.5)
        cr.restore()

        # Right Arm
        cr.save()
        cr.translate(P.arm_attach_x, P.arm_attach_y)
        cr.rotate(self.arm_r_angle)
        draw_capsule(cr, 0, 0, P.arm_shift, P.arm_len, P.arm_r, fill_color=COLOR_FUR, stroke_color=COLOR_OUTLINE, stroke_width=3.5)
        draw_ellipse(cr, P.arm_shift, P.arm_len + 5, P.hand_rx, P.hand_ry, fill_color=COLOR_EAR_INNER, stroke_color=COLOR_OUTLINE, stroke_width=3.5)
        cr.restore()

        # 6. Head & Face
        cr.save()
        cr.translate(0, -78)
        cr.rotate(self.head.local_rot)

        # Big Cute Mouse Ears!
        # Left Ear
        draw_ellipse(cr, -P.ear_x, P.ear_y, P.ear_rx, P.ear_ry, fill_color=COLOR_FUR, stroke_color=COLOR_OUTLINE, stroke_width=4)
        draw_ellipse(cr, -P.ear_x, P.ear_y, P.ear_inner_rx, P.ear_inner_ry, fill_color=COLOR_EAR_INNER)
        # Right Ear
        draw_ellipse(cr, P.ear_x, P.ear_y, P.ear_rx, P.ear_ry, fill_color=COLOR_FUR, stroke_color=COLOR_OUTLINE, stroke_width=4)
        draw_ellipse(cr, P.ear_x, P.ear_y, P.ear_inner_rx, P.ear_inner_ry, fill_color=COLOR_EAR_INNER)

        # Head Base
        draw_ellipse(cr, 0, P.head_center_y, P.head_rx, P.head_ry, fill_color=COLOR_FUR, stroke_color=COLOR_OUTLINE, stroke_width=4)

        # Whiskers (data: shapes.whiskers)
        draw_shape(cr, self.schema.shape("whiskers"), self.schema.palette)

        # Pink Mouse Nose
        draw_ellipse(cr, 0, P.nose_y, P.nose_rx, P.nose_ry, fill_color=COLOR_NOSE, stroke_color=COLOR_OUTLINE, stroke_width=2.5)

        # Mouth
        draw_mouth(cr, self.viseme, self.mouth_open, anchor_y=self.schema.mouth.anchor_y,
                   size=self.schema.mouth.size, stroke_width=self.schema.mouth.stroke_width)

        # Eyes (shared renderer; legacy path when no FaceController is attached)
        draw_eyes(cr, P, self.schema.eyes, colors=self.colors,
                  state=self.eye_state, blink_t=self.blink_t,
                  look_x=self.look_x, look_y=self.look_y,
                  pupil_range=(self.schema.mouth.pupil_x_range,
                               self.schema.mouth.pupil_y_range))

        # Big Round Geek Glasses (Gappu's signature feature!)
        for is_right, lens_x in [(False, -21), (True, 21)]:
            cr.save()
            cr.translate(lens_x, -16 + self.glasses_slide)
            # Glass tint fill
            draw_ellipse(cr, 0, 0, 22, 22, fill_color=COLOR_GLASS_TINT,
                         stroke_color=COLOR_GLASSES, stroke_width=4.5)
            # Lens reflection diagonal glint
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.45)
            cr.set_line_width(2.5)
            cr.move_to(-12, -12); cr.line_to(-4, -4); cr.stroke()
            cr.move_to(4, 4); cr.line_to(12, 12); cr.stroke()
            cr.restore()

        # Glasses bridge across nose
        cr.save()
        cr.translate(0, -16 + self.glasses_slide)
        cr.set_source_rgba(*COLOR_GLASSES)
        cr.set_line_width(4.5)
        cr.move_to(-5, 0); cr.line_to(5, 0); cr.stroke()
        cr.restore()

        # Eyebrows above glasses (expression adds to the pose's brow offset)
        state = self.eye_state
        draw_brows(cr, P, self.schema.eyes, colors=self.colors,
                   y_offset=self.eyebrow_y + (state.brow_y if state else 0.0),
                   tilt_left=self.eyebrow_tilt + (state.brow_tilt_left if state else 0.0),
                   tilt_right=self.eyebrow_tilt + (state.brow_tilt_right if state else 0.0))

        cr.restore()  # Head restore
        cr.restore()  # Torso restore
        cr.restore()  # Main restore
