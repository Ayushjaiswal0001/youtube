"""Dynamic Camera Engine for 2D Animation.
Provides zoom, smooth tracking pan, and impact screen shake.
"""

import math
import random
from typing import Tuple
import cairo

class Camera:
    """Controls viewport transformation (pan, zoom, shake)."""

    def __init__(self, viewport_w: int = 1080, viewport_h: int = 1920):
        self.vw = viewport_w
        self.vh = viewport_h
        self.center_x = viewport_w / 2.0
        self.center_y = viewport_h / 2.0

        # State
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.shake_trauma = 0.0  # 0.0 to 1.0

    def trigger_shake(self, trauma: float = 0.6):
        """Triggers an impact screen shake (e.g. on landing or punchline)."""
        self.shake_trauma = min(1.0, self.shake_trauma + trauma)

    def update(self, dt: float):
        """Damps shake trauma over time."""
        if self.shake_trauma > 0.001:
            self.shake_trauma = max(0.0, self.shake_trauma - dt * 2.5)
        else:
            self.shake_trauma = 0.0

    def apply(self, cr: cairo.Context, t: float):
        """Applies current camera transform to Cairo context."""
        # Calculate screen shake displacement
        shake_x = 0.0
        shake_y = 0.0
        if self.shake_trauma > 0:
            intensity = self.shake_trauma ** 2
            shake_x = math.sin(t * 55.0) * 25.0 * intensity
            shake_y = math.cos(t * 65.0) * 20.0 * intensity

        # Transform around viewport center
        cr.translate(self.center_x + shake_x, self.center_y + shake_y)
        cr.scale(self.zoom, self.zoom)
        cr.translate(-self.center_x - self.pan_x, -self.center_y - self.pan_y)
