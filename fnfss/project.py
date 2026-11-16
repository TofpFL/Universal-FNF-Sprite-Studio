""".RCHR project persistence.

A "project" is an ordinary .rchr archive with a `fnfss/project.json` entry
plus one PNG per animation frame under `project/frames/`. Optionally the
original GIF/WebP bytes are retained under `project/src/` so the project
can be re-opened and re-aligned later.

Everything the editor changes - positions, per-frame offsets, durations,
alignment config, the shared character origin - lives inside the archive.
No sidecar files.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Optional

from PIL import Image

from . import rchr
from .gifproc import Animation, Frame

PROJECT_JSON = "fnfss/project.json"
SCHEMA = 1


def is_project(path) -> bool:
    try:
        return PROJECT_JSON in {e.path for e in rchr.Archive(path).entries}
    except Exception:
        return False


def _frame_png(frame: Frame) -> bytes:
    buf = io.BytesIO()
    frame.image.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def project_files(animations: list[Animation], char_name: str,
                  origin: tuple[float, float], keep_source: bool = True
                  ) -> list[tuple[str, bytes]]:
    """Builds the (arcname, bytes) list for a project archive."""
    files: list[tuple[str, bytes]] = []
    anims_meta = []
    for ai, a in enumerate(animations):
        if not a.frames:
            continue
        from . import gifproc
        gifproc.align(a)
        frames_meta = []
        for fi, f in enumerate(a.frames):
            arc = f"project/frames/{ai}_{fi}.png"
            files.append((arc, _frame_png(f)))
            frames_meta.append({
                "bbox": list(f.bbox),
                "dur": int(f.duration_ms),
                "user": [round(f.user_dx, 3), round(f.user_dy, 3)],
                "img": arc,
            })
        anims_meta.append({
            "name": a.name,
            "prefix": a.prefix,
            "fps": a.fps,
            "loop": a.loop,
            "pos": [round(a.pos_x, 3), round(a.pos_y, 3)],
            "offset": [round(a.offset_x, 3), round(a.offset_y, 3)],
            "frameIndices": a.selected_indices,
            "cur_frame": a.cur_frame,
            "source": a.source,
            "frames": frames_meta,
        })
        if keep_source and a.source_bytes:
            ext = ".gif"
            head = a.source_bytes[:12]
            if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
                ext = ".webp"
            elif head[:8] == b"\x89PNG\r\n\x1a\n":
                ext = ".png"
            files.append((f"project/src/{ai}_src{ext}", a.source_bytes))

    meta = {
        "app": "fnfss",
        "schema": SCHEMA,
        "charName": char_name,
        "origin": [round(origin[0], 3), round(origin[1], 3)],
        "animations": anims_meta,
    }
    files.insert(0, (PROJECT_JSON, json.dumps(meta, indent=1).encode("utf-8")))
    return files


def save_project(path, animations: list[Animation], char_name: str,
                 origin: tuple[float, float], keep_source: bool = True) -> dict:
    return rchr.pack(path, project_files(animations, char_name, origin, keep_source))


def load_project(path) -> tuple[list[Animation], str, tuple[float, float]]:
    """Restores the full editing state from a project .rchr.

    Returns (animations, char_name, origin).
    """
    arch = rchr.Archive(path)
    try:
        meta = json.loads(arch.read(PROJECT_JSON).decode("utf-8"))
    except rchr.RchrError as e:
        raise ValueError(f"not a sprite project: {e}") from e
    if meta.get("schema") != SCHEMA:
        raise ValueError(f"unsupported project schema {meta.get('schema')}")

    char_name = str(meta.get("charName") or "character")
    org = meta.get("origin") or [0, 0]
    origin = (float(org[0]), float(org[1]))

    anims: list[Animation] = []
    src_entries = {e.path: e for e in arch.entries
                   if e.path.startswith("project/src/")}
    for ai, am in enumerate(meta.get("animations", [])):
        a = Animation(name=str(am.get("name") or "anim"),
                      prefix=str(am.get("prefix") or ""),
                      fps=float(am.get("fps") or 24.0),
                      loop=bool(am.get("loop", True)),
                      source=str(am.get("source") or ""))
        pos = am.get("pos") or [0, 0]
        a.pos_x, a.pos_y = float(pos[0]), float(pos[1])
        off = am.get("offset") or [0, 0]
        a.offset_x, a.offset_y = float(off[0]), float(off[1])
        a.cur_frame = int(am.get("cur_frame") or 0)
        sel = am.get("frameIndices") or []
        a.frame_indices = [int(i) for i in sel]

        for fm in am.get("frames", []):
            img_arc = str(fm.get("img") or "")
            try:
                img = Image.open(io.BytesIO(arch.read(img_arc))).convert("RGBA")
            except Exception as e:  # noqa: BLE001
                raise ValueError(f"missing frame image {img_arc}: {e}") from e
            bb = fm.get("bbox") or [0, 0, img.width, img.height]
            usr = fm.get("user") or [0, 0]
            a.frames.append(Frame(
                image=img,
                bbox=(int(bb[0]), int(bb[1]), int(bb[2]), int(bb[3])),
                duration_ms=int(fm.get("dur") or 100),
                user_dx=float(usr[0]), user_dy=float(usr[1]),
            ))
        if a.frames:
            from . import gifproc
            gifproc.align(a)
            # restore retained source bytes if present
            for path, e in src_entries.items():
                stem = path.rsplit("/", 1)[-1]
                if stem.startswith(f"{ai}_src.") or stem.startswith(f"{ai}_src"):
                    try:
                        a.source_bytes = arch.read_entry(e)
                    except Exception:  # noqa: BLE001
                        pass
                    break
            anims.append(a)
    return anims, char_name, origin
