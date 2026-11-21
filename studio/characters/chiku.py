"""Chiku (चीकू) Character Rig - Reusable 2D Vector Animation.
The cheeky, energetic monkey protagonist.
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
    ease_in_out_quad, ease_out_bounce, spring_overshoot
)

# Palette, proportions and timings are data: content/characters/chiku.json
CHIKU_SCHEMA: CharacterSchema = load_schema("chiku")

COLOR_FUR = CHIKU_SCHEMA.color("fur")
COLOR_FUR_DARK = CHIKU_SCHEMA.color("fur_dark")
COLOR_MUZZLE = CHIKU_SCHEMA.color("muzzle")
COLOR_INNER_EAR = CHIKU_SCHEMA.color("inner_ear")
COLOR_VEST = CHIKU_SCHEMA.color("vest")
COLOR_VEST_TRIM = CHIKU_SCHEMA.color("vest_trim")
COLOR_EYE_WHITE = CHIKU_SCHEMA.color("eye_white")
COLOR_PUPIL = CHIKU_SCHEMA.color("pupil")
COLOR_NOSE = CHIKU_SCHEMA.color("nose")
COLOR_SHADOW = CHIKU_SCHEMA.color("shadow")
COLOR_OUTLINE = CHIKU_SCHEMA.color("outline")


class ChikuRig:
    """Reusable 2D skeletal rig for Chiku the Monkey."""

    def __init__(self, x: float | None = None, y: float | None = None,
                 scale: float | None = None, schema: CharacterSchema | None = None):
        self.schema = schema or CHIKU_SCHEMA
        self.prop = self.schema.proportions
        self.timing = self.schema.timing
        self.x = self.schema.anchor["x"] if x is None else x
        self.y = self.schema.anchor["y"] if y is None else y
        self.scale = self.schema.anchor["scale"] if scale is None else scale
        self.facing = 1.0  # 1.0 = right, -1.0 = left

        # Joint Transforms (geometry from the character schema)
        self.root = JointNode("root", local_x=self.x, local_y=self.y)
        self.torso = JointNode("torso", parent=self.root, local_y=self.prop.torso_y)
        self.head = JointNode("head", parent=self.torso, local_y=self.prop.head_joint_y)

        # Facial State
        self.blink_t = 0.0  # 0.0 = open, 1.0 = closed
        self.look_x = 0.0   # -1.0 to 1.0
        self.look_y = 0.0   # -1.0 to 1.0
        self.eyebrow_tilt = 0.0  # radians
        self.eyebrow_y = 0.0
        self.viseme = Viseme.SMILE
        self.mouth_open = 0.0  # 0.0 to 1.0 for talking
        # Set by FaceController (T32). When None the original eye rendering is used, so
        # golden frames and older callers keep their exact look.
        self.eye_state = None

        # Limb Angles (radians)
        self.arm_l_angle = 0.2
        self.arm_r_angle = -0.2
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
        """Update rig joints based on procedural motion and named pose."""
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
        self.arm_l_angle = 0.2
        self.arm_r_angle = -0.2
        self.eyebrow_y = 0.0
        self.eyebrow_tilt = 0.0

        # Talking mouth animation: driven by the narration envelope when a track is
        # supplied, so the mouth follows real speech instead of a fixed 14 Hz wave.
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

        # Named Poses
        if pose == "idle":
            self.head.local_rot = math.sin(t * 2.0) * 0.05
            self.arm_l_angle = 0.15 + math.sin(t * 2.5) * 0.08
            self.arm_r_angle = -0.15 - math.sin(t * 2.5) * 0.08
            self.leg_l_angle = 0.0
            self.leg_r_angle = 0.0
            self.jump_y = 0.0
            self.eyebrow_tilt = 0.05
            self.eyebrow_y = 0.0

        elif pose == "excited_jump":
            jump_cycle = (t * 4.0) % math.pi
            self.jump_y = -abs(math.sin(jump_cycle)) * 60.0
            self.head.local_rot = math.sin(t * 8.0) * 0.1
            self.arm_l_angle = -1.2 + math.sin(t * 8.0) * 0.4  # arms raised high in joy
            self.arm_r_angle = 1.2 - math.sin(t * 8.0) * 0.4
            self.leg_l_angle = -0.3
            self.leg_r_angle = 0.3
            self.tail_wave = math.sin(t * 8.0) * 0.5
            self.eyebrow_y = -8.0
            self.eyebrow_tilt = 0.15
            if not is_talking:
                self.viseme = Viseme.OPEN_WIDE

        elif pose == "boast_proud":
            # Hand on hip, other pointing to chest
            self.jump_y = 0.0
            self.head.local_rot = -0.12  # tilted up proudly
            self.arm_l_angle = -0.8      # pointing proudly
            self.arm_r_angle = 0.7       # hand on hip
            self.leg_l_angle = -0.1
            self.leg_r_angle = 0.1
            self.eyebrow_y = -5.0
            self.eyebrow_tilt = 0.2
            if not is_talking:
                self.viseme = Viseme.SMILE

        elif pose == "shocked_freeze":
            self.jump_y = -10.0
            self.head.local_rot = 0.0
            self.arm_l_angle = -1.4  # hands up on head
            self.arm_r_angle = 1.4
            self.leg_l_angle = -0.05
            self.leg_r_angle = 0.05
            self.eyebrow_y = -15.0   # high shocked brows
            self.eyebrow_tilt = 0.35
            self.blink_t = 0.0       # eyes wide open!
            if not is_talking:
                self.viseme = Viseme.SURPRISED

        elif pose == "embarrassed_smile":
            self.jump_y = 0.0
            self.head.local_rot = 0.15  # tilted shyly
            self.arm_l_angle = -0.2
            self.arm_r_angle = -1.2     # scratching head
            self.leg_l_angle = 0.05
            self.leg_r_angle = -0.05
            self.eyebrow_y = 3.0
            self.eyebrow_tilt = -0.1
            if not is_talking:
                self.viseme = Viseme.SMILE

        elif pose == "spinning_slip":
            self.jump_y = -30.0 + math.sin(t * 12.0) * 15.0
            self.head.local_rot = math.sin(t * 16.0) * 0.5
            self.arm_l_angle = math.sin(t * 14.0) * 1.5
            self.arm_r_angle = -math.sin(t * 14.0) * 1.5
            self.leg_l_angle = math.cos(t * 14.0) * 1.0
            self.leg_r_angle = -math.cos(t * 14.0) * 1.0
            self.eyebrow_y = -10.0
            self.eyebrow_tilt = -0.2

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
        """Renders full 2D vector monkey to Cairo context."""
        cr.save()
        cr.translate(self.x + self.hip_x, self.y + self.jump_y)
        cr.scale(self.scale * self.facing, self.scale * self.squash)

        # 1. Ground Shadow (scales smaller and fades when jumping)
        P = self.prop
        shadow_scale = max(0.4, 1.0 - abs(self.jump_y) / 100.0)
        draw_ellipse(cr, 0, 0, P.shadow_rx * shadow_scale, P.shadow_ry * shadow_scale,
                     fill_color=(0.1, 0.1, 0.15, 0.25 * shadow_scale))

        # 2. Tail (data: shapes.tail, wags with the timing profile)
        draw_shape(cr, self.schema.shape("tail"), self.schema.palette, wave=self.tail_wave)

        # 3. Legs
        # Left Leg (back)
        cr.save()
        cr.translate(-P.leg_attach_x, P.leg_attach_y)
        cr.rotate(self.leg_l_angle)
        draw_capsule(cr, 0, 0, 0, P.leg_len, P.leg_r, fill_color=COLOR_FUR, stroke_color=COLOR_OUTLINE, stroke_width=4)
        # Foot
        draw_ellipse(cr, 8, P.leg_len + 5, P.foot_rx, P.foot_ry, fill_color=COLOR_MUZZLE, stroke_color=COLOR_OUTLINE, stroke_width=4)
        cr.restore()

        # Right Leg (front)
        cr.save()
        cr.translate(P.leg_attach_x, P.leg_attach_y)
        cr.rotate(self.leg_r_angle)
        draw_capsule(cr, 0, 0, 0, P.leg_len, P.leg_r, fill_color=COLOR_FUR, stroke_color=COLOR_OUTLINE, stroke_width=4)
        # Foot
        draw_ellipse(cr, 8, P.leg_len + 5, P.foot_rx, P.foot_ry, fill_color=COLOR_MUZZLE, stroke_color=COLOR_OUTLINE, stroke_width=4)
        cr.restore()

        # 4. Torso with Red Vest
        cr.save()
        cr.translate(0, self.torso.local_y + P.torso_draw_offset)
        cr.rotate(self.torso.local_rot)

        # Body fur base
        draw_ellipse(cr, 0, 0, P.torso_rx, P.torso_ry, fill_color=COLOR_FUR, stroke_color=COLOR_OUTLINE, stroke_width=4)

        # Peach chest patch
        draw_shape(cr, self.schema.shape("chest_patch"), self.schema.palette)

        # Red Cartoon Vest (data: shapes.vest, one panel mirrored for the other side)
        draw_shape(cr, self.schema.shape("vest"), self.schema.palette)
        draw_shape(cr, self.schema.shape("buttons"), self.schema.palette)

        # 5. Arms
        # Left Arm
        cr.save()
        cr.translate(-P.arm_attach_x, P.arm_attach_y)
        cr.rotate(self.arm_l_angle)
        draw_capsule(cr, 0, 0, -P.arm_shift, P.arm_len, P.arm_r, fill_color=COLOR_FUR, stroke_color=COLOR_OUTLINE, stroke_width=4)
        draw_ellipse(cr, -P.arm_shift - 1, P.arm_len + 5, P.hand_rx, P.hand_ry, fill_color=COLOR_MUZZLE, stroke_color=COLOR_OUTLINE, stroke_width=4)
        cr.restore()

        # Right Arm
        cr.save()
        cr.translate(P.arm_attach_x, P.arm_attach_y)
        cr.rotate(self.arm_r_angle)
        draw_capsule(cr, 0, 0, P.arm_shift, P.arm_len, P.arm_r, fill_color=COLOR_FUR, stroke_color=COLOR_OUTLINE, stroke_width=4)
        draw_ellipse(cr, P.arm_shift + 1, P.arm_len + 5, P.hand_rx, P.hand_ry, fill_color=COLOR_MUZZLE, stroke_color=COLOR_OUTLINE, stroke_width=4)
        cr.restore()

        # 6. Head & Face
        cr.save()
        cr.translate(0, P.head_draw_y)
        cr.rotate(self.head.local_rot)

        # Ears
        # Left Ear
        draw_ellipse(cr, -P.ear_x, P.ear_y, P.ear_rx, P.ear_ry, fill_color=COLOR_FUR, stroke_color=COLOR_OUTLINE, stroke_width=4)
        draw_ellipse(cr, -P.ear_x, P.ear_y, P.ear_inner_rx, P.ear_inner_ry, fill_color=COLOR_INNER_EAR)
        # Right Ear
        draw_ellipse(cr, P.ear_x, P.ear_y, P.ear_rx, P.ear_ry, fill_color=COLOR_FUR, stroke_color=COLOR_OUTLINE, stroke_width=4)
        draw_ellipse(cr, P.ear_x, P.ear_y, P.ear_inner_rx, P.ear_inner_ry, fill_color=COLOR_INNER_EAR)

        # Main Head Circle
        draw_ellipse(cr, 0, P.head_center_y, P.head_rx, P.head_ry, fill_color=COLOR_FUR, stroke_color=COLOR_OUTLINE, stroke_width=4)

        # Cute hair tuft on top (data: shapes.hair_tuft)
        draw_shape(cr, self.schema.shape("hair_tuft"), self.schema.palette)

        # Peach Face Muzzle Mask
        cr.save()
        cr.translate(0, P.muzzle_y)
        draw_ellipse(cr, 0, 0, P.muzzle_rx, P.muzzle_ry, fill_color=COLOR_MUZZLE, stroke_color=COLOR_OUTLINE, stroke_width=3.5)

        # Nose
        draw_ellipse(cr, 0, P.nose_y, P.nose_rx, P.nose_ry, fill_color=COLOR_NOSE)
        # Nose shine
        draw_shape(cr, self.schema.shape("nose_shine"), self.schema.palette)

        # Mouth: shape comes from the viseme timeline, amplitude from the narration.
        draw_mouth(cr, self.viseme, self.mouth_open, anchor_y=self.schema.mouth.anchor_y,
                   size=self.schema.mouth.size, stroke_width=self.schema.mouth.stroke_width)

        cr.restore()  # restore muzzle

        # Eyes (shared renderer; legacy path when no FaceController is attached)
        draw_eyes(cr, P, self.schema.eyes, colors=self.colors,
                  state=self.eye_state, blink_t=self.blink_t,
                  look_x=self.look_x, look_y=self.look_y,
                  pupil_range=(self.schema.mouth.pupil_x_range,
                               self.schema.mouth.pupil_y_range))

        # Eyebrows (expression adds to the pose's brow offset)
        state = self.eye_state
        draw_brows(cr, P, self.schema.eyes, colors=self.colors,
                   y_offset=self.eyebrow_y + (state.brow_y if state else 0.0),
                   tilt_left=self.eyebrow_tilt + (state.brow_tilt_left if state else 0.0),
                   tilt_right=self.eyebrow_tilt + (state.brow_tilt_right if state else 0.0))

        cr.restore()  # Head restore
        cr.restore()  # Torso restore
        cr.restore()  # Main restore
