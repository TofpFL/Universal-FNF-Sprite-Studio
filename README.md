# UNIVERSAL: FNF Sprite Studio

Extract, align, preview and export Friday Night Funkin' character sprites —
including native `.RCHR` archive support compatible with the R-Slice engine.

## Run

```
pip install -r requirements.txt
python -m fnfss
```

Or double-click `run.bat`.

**New here? Read [TUTORIAL.md](TUTORIAL.md) — a full walkthrough from
importing GIFs to exporting engine-ready packs.**

## Features

- **Import tab** — paste a Funkipedia (Fandom) character URL to discover
  GIF/PNG assets (thumbnails metadata: size, frames, duration, category).
  Nothing downloads until you select and press *Import selected*. Manual
  GIF/PNG URLs also work.
- **Editor tab** — a borderless 2D workspace with its own camera:
  - **Viewport**: wheel zooms toward the cursor, middle-drag pans,
    double-click empty space resets, `+`/`-`/`0` zoom/reset, `Space`
    plays, `[`/`]` switch animations. Sprites drag freely; the selected
    sprite gets a dashed outline and a transform gizmo (centre = free
    move, X/Y handles = axis-locked). Arrow keys nudge (Shift = ×8).
  - **Positioning layers**: shared *character origin* (crosshair),
    per-animation *position* (anchor point in workspace coords), and
    per-frame *offsets* — three independent layers that never overwrite
    each other.
  - **Timeline**: every frame as a thumbnail with click/ctrl/shift
    multi-select, play/pause/step/scrub, speed control, per-frame
    duration editing.
  - **Ghost overlay**: previous frame drawn semi-transparent under the
    playhead to spot jitter; opacity adjustable.
  - **Stabilize…**: auto-align assistant — measures each frame's visual
    centroid, suggests nudges for frames drifting >2px from the median,
    with preview-before-apply.
  - **Undo/redo** for every edit (camera moves are never recorded).
- **Projects** — *Save project* writes a `.rchr` containing
  `fnfss/project.json` + per-frame PNGs (+ optional original GIFs), so
  every adjustment reopens exactly. *Open project* works from the editor
  toolbar or the RCHR tab. Plain character packs are unaffected.
- **Export tab** — optimized spritesheet PNG + Sparrow-compatible XML +
  character JSON. Two presets: `psych` (Psych Engine schema) and `fnf`
  (modern FNF/V-Slice schema) — they are NOT interchangeable.
- **Pack .RCHR** — writes `characters/<name>.{png,xml,json}` into a `.rchr`
  archive that `raid_engine rchr` and R-Slice mount natively.
- **RCHR tab** — open any `.rchr`, list entries, extract all/selected.

## .RCHR format

Byte-compatible with `gh::rchr` (R-Slice engine): 96-byte header, name
blob, 40-byte index records, raw or zlib-deflate payloads, CRC32
integrity. See `fnfss/rchr.py` docstring for the full layout.
