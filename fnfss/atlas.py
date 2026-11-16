"""Export: spritesheet PNG + Sparrow XML + character JSON presets.

Two JSON presets are supported because the schemas are NOT interchangeable:

- "psych":    Psych Engine character format - animations keyed by name with
              prefix/fps/loop/frameIndices and a shared offset.
- "fnf":      Modern FNF / V-Slice style - frames carry sheet coords and
              per-frame offsets.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape

from PIL import Image

from . import gifproc
from .gifproc import Animation


@dataclass
class SheetFrame:
    anim: str
    index: int                # index into anim.frames
    x: int
    y: int
    w: int
    h: int
    offset_x: int             # placement on the shared canvas
    offset_y: int


@dataclass
class Sheet:
    image: Image.Image
    frames: list[SheetFrame]  # one entry per *selected* animation frame
    width: int
    height: int
    padding: int = 2


def pack_sheet(animations: list[Animation], padding: int = 2,
               max_width: int = 4096) -> Sheet:
    """Shelf-packs every selected frame of every animation into one atlas.

    Frames are NOT trimmed again - each entry is the animation's full shared
    canvas, so offsets stay meaningful across animations of the same char.
    """
    items: list[tuple[Animation, int, Image.Image]] = []
    for a in animations:
        if not a.frames:
            continue
        gifproc.align(a)
        for i in a.selected_indices:
            items.append((a, i, gifproc.render_frame(a, i)))
    if not items:
        raise ValueError("no frames to export")

    # Shelf pack: sort by height desc for tighter packing.
    items.sort(key=lambda t: -t[2].height)
    x = y = row_h = 0
    placements: list[tuple[int, int]] = []
    for _a, _i, img in items:
        if x + img.width + padding > max_width and x > 0:
            x = 0
            y += row_h + padding
            row_h = 0
        placements.append((x, y))
        x += img.width + padding
        row_h = max(row_h, img.height)
    total_w = max(px + img.width for (px, _py), (_a, _i, img) in zip(placements, items)) + padding
    total_h = y + row_h + padding

    sheet = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    frames: list[SheetFrame] = []
    for (a, i, img), (px, py) in zip(items, placements):
        sheet.paste(img, (px, py), img)
        frames.append(SheetFrame(anim=a.name, index=i, x=px, y=py,
                                 w=img.width, h=img.height,
                                 offset_x=0, offset_y=0))
    return Sheet(sheet, frames, total_w, total_h, padding)


def write_png(sheet: Sheet, path: PathLike) -> None:
    sheet.image.save(path, "PNG", optimize=True)


def write_xml(sheet: Sheet, path: PathLike, image_name: str) -> None:
    """Sparrow/Starling atlas XML - the format Psych Engine consumes."""
    lines = ['<?xml version="1.0" encoding="utf-8"?>',
             '<TextureAtlas imageFile="%s">' % escape(image_name)]
    for f in sheet.frames:
        lines.append(
            '  <SubTexture name="%s_%d" x="%d" y="%d" width="%d" height="%d"/>'
            % (escape(f.anim), f.index, f.x, f.y, f.w, f.h))
    lines.append("</TextureAtlas>")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ JSON --

def _clean_name(s: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in s).strip("-").lower() or "anim"


def export_psych_json(animations: list[Animation], char_name: str) -> dict:
    """Psych Engine character JSON (animations block).

    Schema follows Psych's characters/*.json: each animation has a name,
    frame prefix, animType (loop/once), fps, frameIndices into the prefix
    strip, and a shared [x, y] offset in source pixels.
    """
    anims = []
    for a in animations:
        if not a.frames:
            continue
        gifproc.align(a)
        prefix = a.prefix or _clean_name(a.name)
        # Engine anim offset = workspace position of the shared anchor.
        # Per-frame user offsets are already baked into the sheet pixels.
        anims.append({
            "name": a.name,
            "prefix": prefix,
            "animType": "loop" if a.loop else "once",
            "fps": a.fps,
            "frameIndices": a.selected_indices,
            "offsets": [round(a.pos_x, 2), round(a.pos_y, 2)],
            "offset": [round(a.pos_x, 2), round(a.pos_y, 2)],
            "frameCount": len(a.selected_indices),
        })
    return {
        "character": char_name,
        "format": "psych-character",
        "version": "1.0",
        "animations": anims,
    }


def export_fnf_json(sheet: Sheet, animations: list[Animation], char_name: str) -> dict:
    """Modern FNF / V-Slice style character JSON.

    Frames reference the atlas by name and carry per-frame offsets so the
    renderer can place them without re-deriving alignment.
    """
    frame_map: dict[tuple[str, int], dict] = {}
    for f in sheet.frames:
        frame_map[(f.anim, f.index)] = {
            "x": f.x, "y": f.y, "w": f.w, "h": f.h,
            "offsetX": f.offset_x, "offsetY": f.offset_y,
        }
    anims = {}
    for a in animations:
        if not a.frames:
            continue
        sel = a.selected_indices
        anims[_clean_name(a.name)] = {
            "frameRate": a.fps,
            "looped": a.loop,
            "frames": [{"sheet": "sheet", "name": f"{a.name}_{i}",
                        **frame_map.get((a.name, i), {})} for i in sel],
            "offsets": [round(a.pos_x, 2), round(a.pos_y, 2)],
            "offset": [round(a.pos_x, 2), round(a.pos_y, 2)],
        }
    return {
        "character": char_name,
        "format": "fnf-character",
        "version": "1.0",
        "sheet": {"file": f"{char_name}.png", "width": sheet.width, "height": sheet.height},
        "animations": anims,
    }


def write_json(data: dict, path: PathLike) -> None:
    Path(path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def export_warnings(animations: list[Animation]) -> list[str]:
    """Things the target formats cannot represent directly.

    Per-frame user offsets are baked into the spritesheet pixels, so they
    survive every preset - but callers should surface this to the user.
    """
    baked = sum(1 for a in animations for f in a.frames
                if f.user_dx or f.user_dy)
    if not baked:
        return []
    return [f"{baked} per-frame offset(s) baked into the spritesheet "
            "(neither preset has per-frame offset fields)"]


def export_all(animations: list[Animation], out_dir: PathLike, char_name: str,
               preset: str = "psych", atlas_name: Optional[str] = None) -> dict:
    """Writes PNG + XML + JSON into out_dir. Returns written paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    char_name = char_name or "character"
    atlas_name = atlas_name or f"{char_name}.png"

    sheet = pack_sheet(animations)
    png_path = out / atlas_name
    xml_path = out / (Path(atlas_name).stem + ".xml")
    json_path = out / f"{char_name}.json"

    write_png(sheet, png_path)
    write_xml(sheet, xml_path, atlas_name)
    data = (export_psych_json(animations, char_name) if preset == "psych"
            else export_fnf_json(sheet, animations, char_name))
    write_json(data, json_path)
    res = {"png": str(png_path), "xml": str(xml_path), "json": str(json_path),
           "frames": len(sheet.frames), "size": (sheet.width, sheet.height),
           "warnings": export_warnings(animations)}
    return res


# ------------------------------------------------------------------ RCHR --

def pack_character_rchr(animations: list[Animation], out_path: PathLike,
                        char_name: str) -> dict:
    """Builds a .rchr archive containing the exported character files.

    Layout mirrors engine character packs:
        characters/<name>.json
        characters/<name>.png   (atlas)
        characters/<name>.xml   (atlas metadata)
    """
    from . import rchr
    import io, tempfile, os

    char_name = char_name or "character"
    sheet = pack_sheet(animations)

    files: list[tuple[str, bytes]] = []
    buf = io.BytesIO()
    sheet.image.save(buf, "PNG", optimize=True)
    files.append((f"characters/{char_name}.png", buf.getvalue()))

    buf = io.BytesIO()
    # XML as text
    import xml.sax.saxutils as _sx
    lines = ['<?xml version="1.0" encoding="utf-8"?>',
             f'<TextureAtlas imageFile="{char_name}.png">']
    for f in sheet.frames:
        lines.append('  <SubTexture name="%s_%d" x="%d" y="%d" width="%d" height="%d"/>'
                     % (_sx.escape(f.anim), f.index, f.x, f.y, f.w, f.h))
    lines.append("</TextureAtlas>")
    files.append((f"characters/{char_name}.xml", ("\n".join(lines) + "\n").encode("utf-8")))

    files.append((f"characters/{char_name}.json",
                  json.dumps(export_psych_json(animations, char_name), indent=2).encode("utf-8")))

    return rchr.pack(out_path, files)
