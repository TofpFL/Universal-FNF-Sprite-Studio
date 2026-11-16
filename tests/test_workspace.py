"""Tests for workspace camera transforms and .rchr project persistence."""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from fnfss import gifproc, project
from fnfss.camera import Camera


def make_gif(frames: int = 4, size: tuple = (40, 60)) -> bytes:
    imgs = []
    for i in range(frames):
        im = Image.new("RGBA", size, (0, 0, 0, 0))
        # moving square so each frame has a distinct bbox
        x = 5 + i * 3
        for yy in range(10, 30):
            for xx in range(x, x + 10):
                im.putpixel((xx, yy), (255, 0, 0, 255))
        imgs.append(im)
    buf = io.BytesIO()
    imgs[0].save(buf, "GIF", save_all=True, append_images=imgs[1:],
                 duration=80, loop=0, disposal=1)
    return buf.getvalue()


def test_camera_roundtrip():
    c = Camera()
    c.x, c.y, c.zoom = 123.5, -45.0, 3.7
    vw, vh = 800.0, 600.0
    for wpt in [(0, 0), (100, -50), (-999, 1234), (c.x, c.y)]:
        sx, sy = c.w2s(wpt[0], wpt[1], vw, vh)
        bx, by = c.s2w(sx, sy, vw, vh)
        assert abs(bx - wpt[0]) < 1e-6 and abs(by - wpt[1]) < 1e-6


def test_zoom_at_cursor_keeps_world_point():
    c = Camera()
    c.x, c.y, c.zoom = 10.0, 20.0, 2.0
    vw, vh = 640.0, 480.0
    cursor = (300.0, 200.0)
    wx, wy = c.s2w(cursor[0], cursor[1], vw, vh)
    c.zoom_at(1.5, cursor, vw, vh)
    sx, sy = c.w2s(wx, wy, vw, vh)
    assert abs(sx - cursor[0]) < 1e-6 and abs(sy - cursor[1]) < 1e-6


def test_zoom_limits():
    c = Camera()
    for _ in range(500):
        c.zoom_at(2.0, (0, 0), 100, 100)
    assert c.zoom <= Camera.MAX_ZOOM
    for _ in range(2000):
        c.zoom_at(0.5, (0, 0), 100, 100)
    assert c.zoom >= Camera.MIN_ZOOM


def test_pan_does_not_touch_zoom():
    c = Camera()
    z = c.zoom
    c.pan_pixels(50, -30)
    assert c.zoom == z


def test_world_position_helpers():
    data = make_gif()
    a = gifproc.load_animation("test", "mem", data)
    gifproc.align(a)
    a.pos_x, a.pos_y = 200.0, 150.0
    x, y, w, h = gifproc.frame_world_rect(a, 0)
    # anchor world pos must equal pos
    ax, ay = a.pos_x, a.pos_y
    acx, acy = a.anchor_canvas
    px, py = a.placements[0]
    # frame top-left world = pos - anchor_canvas + placement
    assert abs(x - (ax - acx + px)) < 1e-6
    assert abs(y - (ay - acy + py)) < 1e-6
    # canvas cell size is the shared canvas
    assert w == a.canvas_size[0] and h == a.canvas_size[1]


def test_frame_user_offsets_move_placement():
    data = make_gif()
    a = gifproc.load_animation("test", "mem", data)
    gifproc.align(a)
    a.pos_x, a.pos_y = 50.0, 50.0
    before = gifproc.frame_world_topleft(a, 0)
    other_before = gifproc.frame_world_topleft(a, 1)
    a.frames[0].user_dx = 7.0
    a.frames[0].user_dy = -3.0
    gifproc.align(a)
    after = gifproc.frame_world_topleft(a, 0)
    other_after = gifproc.frame_world_topleft(a, 1)
    # world position moves by exactly the user offset
    assert abs(after[0] - before[0] - 7.0) < 0.6
    assert abs(after[1] - before[1] + 3.0) < 0.6
    # untouched frames keep their world position (canvas re-anchor cancels)
    assert abs(other_after[0] - other_before[0]) < 1.6
    assert abs(other_after[1] - other_before[1]) < 1.6


def test_project_roundtrip(tmp_path):
    data = make_gif()
    a = gifproc.load_animation("hero", "mem", data)
    gifproc.align(a)
    a.pos_x, a.pos_y = 123.0, -45.0
    a.offset_x, a.offset_y = 2.0, -1.0
    a.frames[0].user_dx, a.frames[0].user_dy = 5.0, 6.0
    a.frames[1].duration_ms = 250
    a.cur_frame = 2
    a.fps = 12.0

    out = tmp_path / "proj.rchr"
    project.save_project(out, [a], "testchar", (10.0, -20.0), keep_source=True)

    anims, char, origin = project.load_project(out)
    assert char == "testchar"
    assert origin == (10.0, -20.0)
    assert len(anims) == 1
    b = anims[0]
    assert b.name == "hero"
    assert abs(b.pos_x - 123.0) < 0.01 and abs(b.pos_y + 45.0) < 0.01
    assert abs(b.offset_x - 2.0) < 0.01 and abs(b.offset_y + 1.0) < 0.01
    assert b.cur_frame == 2
    assert abs(b.fps - 12.0) < 0.01
    assert abs(b.frames[0].user_dx - 5.0) < 0.01
    assert abs(b.frames[0].user_dy - 6.0) < 0.01
    assert b.frames[1].duration_ms == 250
    # placements recomputed identically
    assert b.placements == a.placements
    assert b.canvas_size == a.canvas_size
    # source GIF retained
    assert b.source_bytes  # may be empty on load - frames are authoritative


def test_project_is_project_flag(tmp_path):
    from fnfss import rchr
    data = make_gif()
    a = gifproc.load_animation("x", "mem", data)
    gifproc.align(a)
    p = tmp_path / "plain.rchr"
    # plain character pack (no project.json) must NOT be a project
    atlas_png = io.BytesIO()
    Image.new("RGBA", (4, 4)).save(atlas_png, "PNG")
    rchr.pack(p, [("characters/x.png", atlas_png.getvalue())])
    assert not project.is_project(p)
    p2 = tmp_path / "proj.rchr"
    project.save_project(p2, [a], "x", (0, 0), keep_source=False)
    assert project.is_project(p2)


if __name__ == "__main__":
    import tempfile
    test_camera_roundtrip()
    test_zoom_at_cursor_keeps_world_point()
    test_zoom_limits()
    test_pan_does_not_touch_zoom()
    test_world_position_helpers()
    test_frame_user_offsets_move_placement()
    with tempfile.TemporaryDirectory() as d:
        from pathlib import Path as P
        test_project_roundtrip(P(d))
        test_project_is_project_flag(P(d))
    print("all tests passed")
