# FNF Sprite Studio — Tutorial

A walkthrough of the whole workflow: pulling GIFs off Fandom, cleaning them
up in the workspace, and exporting engine-ready assets.

---

## 1. Importing sprites

Open the **Import** tab.

**From a Fandom/Funkipedia page**

1. Paste the character page URL, e.g.
   `https://fridaynightfunking.fandom.com/wiki/Hatsune_Miku_(DegODraws)`
2. Press **Scan page**. The app queries the MediaWiki API and lists every
   GIF/animated asset on the page — thumbnails, pixel size, frame count,
   duration, and an auto-guessed category (Idle, Sing LEFT/UP/DOWN/RIGHT,
   Miss, etc.).
3. Tick the ones you want and press **Import selected**. Nothing is
   downloaded until you do this.

**From a direct URL**

Paste any GIF/WebP/APNG URL into the manual field and import. Fandom
`?format=original` links work too — that's the canonical way to get the
full-resolution GIF instead of a thumbnail.

Each imported animation lands in the Editor workspace at its own spot.

## 2. The workspace

The **Editor** tab is a borderless 2D canvas — sprites float on the app
background with no frame around them.

### Camera

| Input | Action |
|---|---|
| Mouse wheel | Zoom **toward the cursor** (the world point under your cursor stays put) |
| Middle-mouse drag | Pan |
| Double-click empty space | Reset camera to 1:1 origin |
| `+` / `-` | Zoom in / out |
| `0` | Reset view |
| Zoom % readout (top-right) | Current zoom; click **reset view** to snap back |

The camera never touches sprite data — zoom and pan are pure view state.

### Selecting and moving whole animations

Click a sprite to select it (dashed outline + gizmo appear). In **Move
GIF** mode (View panel):

- **Centre gizmo handle** — free drag anywhere
- **X / Y handles** — axis-locked drags
- **Arrow keys** — nudge 1px, `Shift`+arrow = 8px
- Dragging updates the animation's Position X/Y in the Properties panel

All frames keep their relative layout — you're moving the whole animation
as one unit.

### Positioning layers

Three independent layers, never overwriting each other:

1. **Character origin** — the shared crosshair. Set this once; it's the
   common reference point every animation aligns to.
2. **Animation position** — where each animation's anchor sits in the
   workspace (`pos_x`/`pos_y`).
3. **Frame offsets** — per-frame `user_dx`/`user_dy` corrections on top
   of the native GIF alignment.

## 3. Frame editing

### Timeline

Every frame is a thumbnail cell showing index + duration.

- **Click** — select one frame; **Ctrl+click** toggle; **Shift+click**
  range-select
- **Transport** — `|<` `<` play `>` `>|`, scrub slider, speed 0.1–8×
- The playhead frame always renders at full opacity

### Move Frame mode

Switch the View panel to **Move Frame**, select frame(s) in the timeline
(or click the sprite itself), then drag — only the selected frames move.
Their X/Y offsets update live in Properties and stay synced with the
offset spinboxes. Multi-selected frames drag together.

### Onion-skin ghosting

In the View panel:

- **onion skin (prev frame)** — previous frame at fixed 50% opacity,
  drawn at *its own* position
- **next frame ghost** — same for the next frame, independent toggle

Ghosts respect loop/non-loop boundaries (wrap on looped animations,
stop at the ends otherwise), update instantly when you change frames,
and can never be selected or dragged — they're pure reference.

### Stabilize…

If a GIF jitters frame-to-frame, **Stabilize…** measures each frame's
alpha centroid and suggests nudges for frames drifting >2px from the
median. It shows a preview — tick only the frames you actually want
pulled in, then apply. Every apply is undoable.

> Note: frames keep their *native* GIF alignment by default, so
> intentional motion (bounces, sways) is preserved. Stabilize is for
> fixing genuinely inconsistent frames, not for flattening animation.

### Undo/redo

Every edit — moves, offsets, durations, origin, stabilize — is undoable
(`Ctrl+Z` / `Ctrl+Y`). Camera moves are never recorded.

## 4. Saving and reopening

**Save project** writes a single `.rchr` archive containing
`fnfss/project.json` + every frame PNG + optionally the original GIFs.
Everything — positions, offsets, durations, origin, playhead — reopens
exactly.

**Open project** works from the editor toolbar or the RCHR tab. Plain
character packs (no `project.json`) open as archives, not projects.

## 5. Exporting

The **Export** tab produces three files:

- **Spritesheet PNG** — packed atlas, optimized layout
- **XML** — Sparrow/TexturePacker-compatible frame data
- **JSON** — character definition

Two presets — they are **not** interchangeable:

- `psych` — Psych Engine schema
- `fnf` — modern FNF / V-Slice schema

**Positioning:** the animation's Position exports as the engine's
`offsets` field. Per-frame offsets get *baked into the sheet pixels*
when the target format can't represent them — the export log tells you
when baking happened so nothing is silently dropped.

## 6. Making a character pack

**Pack .RCHR** writes `characters/<name>.{png,xml,json}` into a `.rchr`
that `raid_engine rchr` and R-Slice mount natively — that's the format
your engine reads.

## 7. .RCHR tab

Open any `.rchr` — sprite packs, project files, anything — list its
entries, and extract all or selected files.

---

## Quick reference

| Task | How |
|---|---|
| Find a character's GIFs | Import tab → paste Fandom URL → Scan page |
| Zoom | Wheel (cursor-anchored) / `+` `-` |
| Pan | Middle-drag |
| Reset view | Double-click empty space / `0` |
| Move whole animation | Select sprite, drag in Move GIF mode |
| Move single frames | Timeline select → Move Frame mode → drag |
| Nudge selected | Arrow keys (Shift = ×8) |
| Preview jitter | Onion-skin prev/next ghost at 50% |
| Fix jitter | Stabilize… → preview → apply |
| Save everything | Save project → `.rchr` |
| Engine-ready files | Export tab → pick `psych` or `fnf` |
| Engine character pack | Pack .RCHR |
