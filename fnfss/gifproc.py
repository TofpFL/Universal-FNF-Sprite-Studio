"""GIF frame extraction, bounding-box detection and shared-anchor alignment.

Alignment model: every animation gets ONE shared anchor (the centre of the
union of all frame bounding boxes, plus a user X/Y nudge). Each frame is
then placed so its own bbox centre lands on that anchor - frames never get
independently centred, so the character cannot drift between frames while
intentional in-animation movement (bouncing, stepping) is preserved as
long as it stays inside the shared canvas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Optional

import requests
from PIL import Image


@dataclass
class Frame:
    image: Image.Image          # RGBA, trimmed to its content bbox
    bbox: tuple[int, int, int, int]  # (x0, y0, x1, y1) in source frame px
    duration_ms: int = 100
    dispose: int = 0
    user_dx: float = 0.0        # manual per-frame nudge, canvas pixels
    user_dy: float = 0.0


@dataclass
class Animation:
    name: str
    frames: list[Frame] = field(default_factory=list)
    fps: float = 24.0
    loop: bool = True
    prefix: str = ""             # sprite filename prefix, e.g. "bf"
    frame_indices: list[int] = field(default_factory=list)  # into frames[]
    offset_x: float = 0.0        # manual alignment nudge, canvas pixels
    offset_y: float = 0.0
    pos_x: float = 0.0           # workspace position of the anchor, world px
    pos_y: float = 0.0
    cur_frame: int = 0           # viewport/timeline playhead
    source: str = ""             # origin URL / path for display
    source_bytes: bytes = b""    # original GIF/WebP bytes, for project save

    # filled by align()
    canvas_size: tuple[int, int] = (0, 0)
    anchor: tuple[float, float] = (0.0, 0.0)
    anchor_canvas: tuple[float, float] = (0.0, 0.0)  # anchor pos within canvas
    placements: list[tuple[int, int]] = field(default_factory=list)      # final (incl. user offsets)
    base_placements: list[tuple[int, int]] = field(default_factory=list)  # auto-align only

    # ------------------------------------------------------------ utils --
    @property
    def duration_ms(self) -> int:
        return int(round(1000.0 / self.fps)) if self.fps > 0 else 100

    @property
    def selected_indices(self) -> list[int]:
        if self.frame_indices:
            return [i for i in self.frame_indices if 0 <= i < len(self.frames)]
        return list(range(len(self.frames)))

    def duration_seconds(self) -> float:
        sel = self.selected_indices
        if not sel:
            return 0.0
        # GIF frame durations where present, else fps-derived.
        total = 0.0
        for i in sel:
            d = self.frames[i].duration_ms
            total += d / 1000.0 if d > 0 else 1.0 / max(self.fps, 1.0)
        return total


# ------------------------------------------------------------------ GIF --

# Formats Pillow can step through frame-by-frame. Fandom serves animated
# WebP for many "GIF" links (content negotiation), so WebP is first-class.
ANIM_FORMATS = {"GIF", "WEBP", "PNG"}  # PNG covers APNG


def _iter_gif_frames(img: Image.Image) -> list[Frame]:
    """Extracts every animation frame as a full-size RGBA image.

    Works for GIF, animated WebP and APNG - PIL exposes the same
    seek(n)/info[duration] interface for all of them.
    """
    frames: list[Frame] = []
    width, height = img.size
    index = 0
    while True:
        try:
            img.seek(index)
        except EOFError:
            break
        duration = int(img.info.get("duration", 100) or 100)
        dispose = int(img.info.get("disposal", 0) or 0)
        # Compose onto a full-size canvas so each frame is self-contained.
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        frame = img.convert("RGBA")
        if frame.size != (width, height):
            tmp = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            tmp.paste(frame, (0, 0))
            frame = tmp
        canvas.alpha_composite(frame)
        frames.append(Frame(canvas, (0, 0, width, height), duration, dispose))
        index += 1
    return frames


def content_bbox(im: Image.Image, threshold: int = 8) -> Optional[tuple[int, int, int, int]]:
    """Bounding box of non-transparent pixels (x0, y0, x1, y1 exclusive)."""
    alpha = im.getchannel("A")
    bbox = alpha.point(lambda a: 255 if a > threshold else 0).getbbox()
    return bbox


def load_animation(name: str, source: str, data: bytes,
                   prefix: str = "", fps: float = 24.0) -> Animation:
    """Builds an Animation from GIF/WebP/APNG bytes."""
    img = Image.open(BytesIO(data))
    if img.format not in ANIM_FORMATS:
        raise ValueError(f"unsupported image format: {img.format}")
    frames = _iter_gif_frames(img)
    if len(frames) <= 1 and img.format == "PNG":
        # static PNG - still a valid single-frame "animation"
        pass
    anim = Animation(name=name, source=source, prefix=prefix or _guess_prefix(name),
                     fps=fps, source_bytes=data)
    for fr in frames:
        bb = content_bbox(fr.image)
        if bb is None:
            bb = (0, 0, fr.image.width, fr.image.height)
        # Trim the stored image to its bbox; keep placement math via bbox.
        fr.image = fr.image.crop(bb)
        fr.bbox = bb
        anim.frames.append(fr)
    if not anim.frames:
        raise ValueError("GIF has no frames")
    return anim


def load_animation_path(name: str, path: PathLike, **kw) -> Animation:
    return load_animation(name, str(path), Path(path).read_bytes(), **kw)


def _guess_prefix(name: str) -> str:
    """'bfIdle' -> 'bf', 'bf-left' -> 'bf'."""
    import re
    m = re.match(r"([A-Za-z]+)", name)
    return m.group(1).lower() if m else ""


# ------------------------------------------------------------- alignment --

def align(anim: Animation, padding: int = 4) -> Animation:
    """Computes the shared anchor and per-frame placements.

    anchor = centre of the union of every frame's *source-space* bbox,
    nudged by offset_x/offset_y. Each frame's trimmed image is placed so its
    bbox centre sits on the anchor. Canvas grows to fit every placement.
    """
    if not anim.frames:
        return anim

    # Union bbox in source coordinates (frames may differ in size).
    ux0 = min(f.bbox[0] for f in anim.frames)
    uy0 = min(f.bbox[1] for f in anim.frames)
    ux1 = max(f.bbox[2] for f in anim.frames)
    uy1 = max(f.bbox[3] for f in anim.frames)
    anchor_x = (ux0 + ux1) / 2.0 + anim.offset_x
    anchor_y = (uy0 + uy1) / 2.0 + anim.offset_y
    anim.anchor = (anchor_x, anchor_y)

    # Largest manual frame nudge - canvas grows so user offsets can't clip.
    margin = 2 + int(max([0.0] + [max(abs(f.user_dx), abs(f.user_dy))
                                 for f in anim.frames]))

    base = []
    finals = []
    min_x = min_y = 1 << 30
    max_x = max_y = 0
    for f in anim.frames:
        cx = (f.bbox[0] + f.bbox[2]) / 2.0
        cy = (f.bbox[1] + f.bbox[3]) / 2.0
        # top-left of trimmed image relative to the anchor
        x = anchor_x - (cx - f.bbox[0])
        y = anchor_y - (cy - f.bbox[1])
        bx, by = int(round(x)), int(round(y))
        fx, fy = bx + int(round(f.user_dx)), by + int(round(f.user_dy))
        base.append((bx, by))
        finals.append((fx, fy))
        min_x = min(min_x, fx)
        min_y = min(min_y, fy)
        max_x = max(max_x, fx + f.image.width)
        max_y = max(max_y, fy + f.image.height)
    anim.base_placements = base

    w = max_x - min_x + padding * 2 + margin * 2
    h = max_y - min_y + padding * 2 + margin * 2
    anim.canvas_size = (int(w), int(h))
    # Anchor position within the final canvas (for workspace transforms).
    anim.anchor_canvas = (anchor_x - (min_x - padding - margin),
                          anchor_y - (min_y - padding - margin))
    anim.placements = [(x - min_x + padding + margin, y - min_y + padding + margin)
                       for x, y in finals]
    return anim


def frame_world_topleft(anim: Animation, index: int) -> tuple[float, float]:
    """World-space top-left of a frame's canvas cell.

    pos_* is where the shared anchor sits in world space; the canvas is
    drawn so its anchor_canvas point lands exactly there.
    """
    if not anim.placements or index < 0 or index >= len(anim.placements):
        return (anim.pos_x, anim.pos_y)
    ax, ay = anim.anchor_canvas
    x, y = anim.placements[index]
    return (anim.pos_x - ax + x, anim.pos_y - ay + y)


def frame_world_rect(anim: Animation, index: int) -> tuple[float, float, float, float]:
    """(x, y, w, h) of the frame's canvas cell in world space."""
    x, y = frame_world_topleft(anim, index)
    w, h = anim.canvas_size if anim.canvas_size != (0, 0) else (0, 0)
    return (x, y, float(w), float(h))


def render_frame(anim: Animation, index: int,
                 placements: Optional[list] = None) -> Image.Image:
    """Full RGBA canvas for one frame (for preview)."""
    if not anim.frames or index < 0 or index >= len(anim.frames):
        return Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    if not anim.placements:
        align(anim)
    pl = placements if placements is not None else anim.placements
    if index >= len(pl):
        return Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    canvas = Image.new("RGBA", anim.canvas_size, (0, 0, 0, 0))
    x, y = pl[index]
    canvas.paste(anim.frames[index].image, (x, y), anim.frames[index].image)
    return canvas


def preview_sheet(anim: Animation, max_frames: int = 12) -> Image.Image:
    """Small contact sheet of selected frames for the editor preview."""
    sel = anim.selected_indices[:max_frames]
    if not sel:
        return Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    thumbs = []
    for i in sel:
        t = render_frame(anim, i)
        t.thumbnail((96, 96), Image.LANCZOS)
        thumbs.append(t)
    cols = min(4, len(thumbs))
    rows = (len(thumbs) + cols - 1) // cols
    tw = max(t.width for t in thumbs)
    th = max(t.height for t in thumbs)
    sheet = Image.new("RGBA", (cols * (tw + 4) + 4, rows * (th + 4) + 4), (24, 24, 32, 255))
    for i, t in enumerate(thumbs):
        sheet.paste(t, (4 + (i % cols) * (tw + 4), 4 + (i // cols) * (th + 4)), t)
    return sheet


# ------------------------------------------------------- align assistant --

def alpha_centroid(image: Image.Image) -> Optional[tuple[float, float]]:
    """Alpha-weighted centroid of an RGBA image, in image-local coords."""
    if image.width == 0 or image.height == 0:
        return None
    px = image.load()
    sx = sy = sw = 0.0
    for y in range(image.height):
        for x in range(image.width):
            a = px[x, y][3]
            if a:
                sx += x * a
                sy += y * a
                sw += a
    if sw <= 0:
        return None
    return (sx / sw, sy / sw)


def frame_canvas_centroid(anim: Animation, index: int) -> Optional[tuple[float, float]]:
    """Visual centre of a frame in canvas coordinates (uses final placement)."""
    if not anim.placements or index >= len(anim.placements):
        return None
    c = alpha_centroid(anim.frames[index].image)
    if c is None:
        return None
    x, y = anim.placements[index]
    return (x + c[0], y + c[1])


def suggest_stabilize(anim: Animation, threshold: float = 2.0
                      ) -> dict[int, tuple[float, float]]:
    """Suggests per-frame user offsets that pull visual centroids together.

    auto-align centres each frame's *bbox*, but content inside the bbox can
    still drift (a weapon appearing, a cape moving). This measures the
    alpha centroid of every frame in canvas space and suggests nudges toward
    the median centroid - only for frames deviating more than `threshold`
    pixels. Returns {frame_index: (dx, dy)} to ADD to user_dx/user_dy.
    Nothing is applied automatically; intentional movement is the user's call.
    """
    cents = [frame_canvas_centroid(anim, i) for i in range(len(anim.frames))]
    valid = [c for c in cents if c is not None]
    if len(valid) < 2:
        return {}
    xs = sorted(c[0] for c in valid)
    ys = sorted(c[1] for c in valid)
    mx = xs[len(xs) // 2] if len(xs) % 2 else (xs[len(xs) // 2 - 1] + xs[len(xs) // 2]) / 2
    my = ys[len(ys) // 2] if len(ys) % 2 else (ys[len(ys) // 2 - 1] + ys[len(ys) // 2]) / 2
    out: dict[int, tuple[float, float]] = {}
    for i, c in enumerate(cents):
        if c is None:
            continue
        dx, dy = mx - c[0], my - c[1]
        if abs(dx) > threshold or abs(dy) > threshold:
            out[i] = (round(dx, 2), round(dy, 2))
    return out


# ------------------------------------------------------------ downloading --

def fetch_bytes(url: str, timeout: float = 30.0) -> bytes:
    """Downloads a URL with a browser-ish UA (Fandom requires it)."""
    r = requests.get(url, timeout=timeout,
                     headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                           "FNF-Sprite-Studio/1.0"})
    r.raise_for_status()
    return r.content


def looks_like_animation(url: str) -> bool:
    return url.lower().split("?")[0].endswith((".gif", ".png", ".webp"))
