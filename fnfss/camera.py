"""2D camera for the sprite workspace.

Pure math, no Qt - world <-> screen transforms live here so they can be
unit-tested. Screen coords are pixels with origin top-left; world coords
are source-image pixels with origin at the shared character origin, +y
down (same convention as the sprites).
"""

from __future__ import annotations


class Camera:
    MIN_ZOOM = 0.02
    MAX_ZOOM = 64.0

    def __init__(self) -> None:
        self.x = 0.0          # world coord shown at viewport centre
        self.y = 0.0
        self.zoom = 1.0

    # ---------------------------------------------------------- basics --
    def w2s(self, wx: float, wy: float, vw: float, vh: float) -> tuple[float, float]:
        """World -> screen pixels."""
        return ((wx - self.x) * self.zoom + vw / 2.0,
                (wy - self.y) * self.zoom + vh / 2.0)

    def s2w(self, sx: float, sy: float, vw: float, vh: float) -> tuple[float, float]:
        """Screen pixels -> world."""
        return (self.x + (sx - vw / 2.0) / self.zoom,
                self.y + (sy - vh / 2.0) / self.zoom)

    def pan_pixels(self, dx: float, dy: float) -> None:
        """Pan by a screen-space pixel delta (drag)."""
        self.x -= dx / self.zoom
        self.y -= dy / self.zoom

    def pan_world(self, dx: float, dy: float) -> None:
        """Pan by a world-space delta."""
        self.x += dx
        self.y += dy

    def zoom_at(self, factor: float, cursor: tuple[float, float],
                vw: float, vh: float) -> None:
        """Zoom by `factor`, keeping the world point under `cursor` fixed."""
        wx, wy = self.s2w(cursor[0], cursor[1], vw, vh)
        self.zoom = min(self.MAX_ZOOM, max(self.MIN_ZOOM, self.zoom * factor))
        # Re-derive centre so the grabbed world point stays under the cursor.
        self.x = wx - (cursor[0] - vw / 2.0) / self.zoom
        self.y = wy - (cursor[1] - vh / 2.0) / self.zoom

    def zoom_center(self, factor: float, vw: float, vh: float) -> None:
        self.zoom_at(factor, (vw / 2.0, vh / 2.0), vw, vh)

    def reset(self) -> None:
        self.x = self.y = 0.0
        self.zoom = 1.0

    @property
    def zoom_pct(self) -> int:
        return int(round(self.zoom * 100))
