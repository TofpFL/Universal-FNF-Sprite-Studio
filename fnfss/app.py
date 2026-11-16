"""FNF Sprite Studio - PySide6 GUI.

Tabs: Import (Funkipedia/manual GIF), Editor (align/preview), Export
(PNG/XML/JSON presets + .RCHR pack), RCHR (browse/extract archives).
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QThread, Signal, QElapsedTimer, QRectF, QPointF
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QFont, QPen, QBrush
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QSlider, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem,
    QTabWidget, QTextEdit, QVBoxLayout, QWidget, QHeaderView,
)

from . import atlas, funkipedia, gifproc, project, rchr
from .camera import Camera
from .gifproc import Animation

_BG = QColor(26, 26, 34)
_GRID = QColor(38, 38, 50)
_SEL = QColor(80, 160, 255)
_ORIGIN = QColor(255, 120, 90)
_ANCHOR = QColor(140, 220, 140)


def pil_to_qimage(img) -> QImage:
    img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    q = QImage(data, img.width, img.height, QImage.Format_RGBA8888)
    return q.copy()


class _DiscoverWorker(QThread):
    done = Signal(object)

    def __init__(self, url: str):
        super().__init__()
        self.url = url

    def run(self):
        try:
            self.done.emit(funkipedia.discover(self.url))
        except Exception as e:  # noqa: BLE001
            res = funkipedia.ImportResult()
            res.warnings.append(f"discover failed: {e}")
            self.done.emit(res)


class ImportTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.assets: list[funkipedia.DiscoveredAsset] = []
        self._worker: _DiscoverWorker | None = None
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://character.funkipedia.miraheze.org/wiki/...")
        fetch = QPushButton("Fetch wiki")
        fetch.clicked.connect(self._fetch)
        row.addWidget(QLabel("Wiki URL:"))
        row.addWidget(self.url_edit, 1)
        row.addWidget(fetch)
        lay.addLayout(row)

        row2 = QHBoxLayout()
        self.gif_edit = QLineEdit()
        self.gif_edit.setPlaceholderText("manual GIF/PNG URL")
        add = QPushButton("Add URL")
        add.clicked.connect(self._add_manual)
        row2.addWidget(QLabel("Manual:"))
        row2.addWidget(self.gif_edit, 1)
        row2.addWidget(add)
        lay.addLayout(row2)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["", "Thumb", "Name", "Category", "Size", "Frames", "Duration", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        lay.addWidget(self.table, 1)

        btns = QHBoxLayout()
        for label, fn in [("Select all", lambda: self._set_all(True)),
                          ("Deselect all", lambda: self._set_all(False)),
                          ("Import selected", self._import)]:
            b = QPushButton(label)
            b.clicked.connect(fn)
            btns.addWidget(b)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        btns.addWidget(self.progress)
        lay.addLayout(btns)
        self.status = QLabel("")
        lay.addWidget(self.status)

    # ------------------------------------------------------------- fetch --
    def _fetch(self):
        url = self.url_edit.text().strip()
        if not url or (self._worker and self._worker.isRunning()):
            return
        self.status.setText("Fetching page + probing assets (this can take a bit)...")
        self._worker = _DiscoverWorker(url)
        self._worker.done.connect(self._on_discovered)
        self._worker.start()

    def _on_discovered(self, res):
        self.assets = res.assets
        self._fill_table()
        msg = f"{len(self.assets)} GIF(s) discovered on {res.page_title or self.url_edit.text()}"
        if res.warnings:
            msg = "; ".join(res.warnings) + " | " + msg
        self.status.setText(msg)

    def _add_manual(self):
        url = self.gif_edit.text().strip()
        if not url:
            return
        name = url.rsplit("/", 1)[-1].split("?")[0] or "manual"
        a = funkipedia.DiscoveredAsset(url=url, name=name,
                                       kind="gif" if name.lower().endswith(".gif") else "png",
                                       category=funkipedia.categorise(name),
                                       selected=True)
        self.assets.append(a)
        self._fill_table()
        self.gif_edit.clear()

    def _fill_table(self):
        self.table.setRowCount(len(self.assets))
        for i, a in enumerate(self.assets):
            cb = QCheckBox()
            cb.setChecked(a.selected)
            cb.stateChanged.connect(lambda _s, idx=i, w=cb: setattr(self.assets[idx], "selected", w.isChecked()))
            self.table.setCellWidget(i, 0, cb)
            # thumbnail: first GIF frame captured during the probe
            thumb = QLabel()
            thumb.setFixedSize(76, 76)
            thumb.setAlignment(Qt.AlignCenter)
            thumb.setStyleSheet("background:#22222c;")
            if a.thumb_png:
                pm = QPixmap()
                pm.loadFromData(a.thumb_png, "PNG")
                pm = pm.scaled(72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                thumb.setPixmap(pm)
            self.table.setCellWidget(i, 1, thumb)
            self.table.setItem(i, 2, QTableWidgetItem(a.name))
            self.table.setItem(i, 3, QTableWidgetItem(a.category))
            size = f"{a.width}x{a.height}" if a.width else "?"
            self.table.setItem(i, 4, QTableWidgetItem(size))
            self.table.setItem(i, 5, QTableWidgetItem(str(a.frames) if a.frames else "?"))
            dur = f"{a.duration_ms/1000:.2f}s" if a.duration_ms else "?"
            self.table.setItem(i, 6, QTableWidgetItem(dur))
            self.table.setItem(i, 7, QTableWidgetItem(a.error or "ready"))
        self.table.resizeColumnsToContents()

    def _set_all(self, on: bool):
        for a in self.assets:
            a.selected = on
        self._fill_table()

    # ------------------------------------------------------------ import --
    def _import(self):
        todo = [a for a in self.assets if a.selected]
        if not todo:
            self.status.setText("nothing selected")
            return
        self.progress.setVisible(True)
        self.progress.setMaximum(len(todo))
        ok = 0
        for i, a in enumerate(todo):
            self.progress.setValue(i)
            QApplication.processEvents()
            try:
                anim = funkipedia.import_asset(a)
                self.window().add_animation(anim)
                ok += 1
            except Exception as e:  # noqa: BLE001
                a.error = str(e)
        self.progress.setVisible(False)
        self._fill_table()
        self.status.setText(f"imported {ok}/{len(todo)} animation(s)")


# ------------------------------------------------------------------ undo --

class _LambdaCmd:
    """Minimal undo/redo command (avoids importing QUndoCommand plumbing)."""
    def __init__(self, text, undo, redo):
        self.text = text
        self._u = undo
        self._r = redo

    def undo(self):
        self._u()

    def redo(self):
        self._r()


# ---------------------------------------------------------------- viewport --

class Viewport(QWidget):
    """Borderless window into the infinite 2D workspace.

    Camera state lives entirely in screen space concerns - it never touches
    sprite coordinates. Sprites are drawn in world coordinates through a
    single QTransform.
    """

    def __init__(self, editor: "EditorTab"):
        super().__init__()
        self.editor = editor
        self.camera = Camera()
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._cache: dict = {}
        self._cache_rev = -1
        self._pan = None          # (last_x, last_y) while middle-dragging
        self._drag = None         # active sprite drag state
        self._space_pan = False

    # ------------------------------------------------------------ cache --
    def _frame_image(self, anim: Animation, idx: int) -> QImage:
        """Trimmed sprite QImage - drawn 1:1 in world units (zoom scales)."""
        rev = self.editor.revision
        if self._cache_rev != rev:
            self._cache.clear()
            self._cache_rev = rev
        key = (id(anim), idx)
        img = self._cache.get(key)
        if img is None:
            img = pil_to_qimage(anim.frames[idx].image)
            self._cache[key] = img
        return img

    # ------------------------------------------------------------ paint --
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.fillRect(self.rect(), _BG)
        ed = self.editor
        vw, vh = self.width(), self.height()
        cam = self.camera

        # world transform: screen = (world - cam) * zoom + centre
        p.translate(vw / 2.0, vh / 2.0)
        p.scale(cam.zoom, cam.zoom)
        p.translate(-cam.x, -cam.y)

        # faint workspace grid (world space, every 64px)
        if ed.show_grid:
            pen = QPen(_GRID)
            pen.setWidthF(1.0 / cam.zoom)
            p.setPen(pen)
            step = 64.0
            left = cam.x - vw / 2 / cam.zoom - step
            right = cam.x + vw / 2 / cam.zoom + step
            top = cam.y - vh / 2 / cam.zoom - step
            bottom = cam.y + vh / 2 / cam.zoom + step
            x = left - (left % step)
            while x <= right:
                p.drawLine(QPointF(x, top), QPointF(x, bottom))
                x += step
            y = top - (top % step)
            while y <= bottom:
                p.drawLine(QPointF(left, y), QPointF(right, y))
                y += step

        sel_anim = ed.current_anim()
        # pass 1: non-selected animations
        for a in ed.animations:
            if a is sel_anim:
                continue
            self._draw_anim(p, ed, a, primary_only=True, alpha=0.85)
        # pass 2: selected animation (all selected frames when frame mode)
        if sel_anim is not None:
            self._draw_anim(p, ed, sel_anim, primary_only=False, alpha=1.0)

        # shared character origin crosshair
        if ed.show_origin:
            ox, oy = ed.origin
            pen = QPen(_ORIGIN)
            pen.setWidthF(1.5 / cam.zoom)
            p.setPen(pen)
            r = 10.0 / cam.zoom
            p.drawLine(QPointF(ox - r, oy), QPointF(ox + r, oy))
            p.drawLine(QPointF(ox, oy - r), QPointF(ox, oy + r))
            p.drawEllipse(QPointF(ox, oy), 3.0 / cam.zoom, 3.0 / cam.zoom)

        # anchor points for every animation (selected one highlighted)
        if ed.show_anchors:
            for a in ed.animations:
                col = _SEL if a is sel_anim else _ANCHOR
                pen = QPen(col)
                pen.setWidthF((1.5 if a is sel_anim else 1.0) / cam.zoom)
                p.setPen(pen)
                ax, ay = a.pos_x, a.pos_y
                r = (7.0 if a is sel_anim else 4.0) / cam.zoom
                p.drawLine(QPointF(ax - r, ay), QPointF(ax + r, ay))
                p.drawLine(QPointF(ax, ay - r), QPointF(ax, ay + r))

        p.resetTransform()  # back to screen space for gizmo

        # selection outline (world space) + gizmo (screen space)
        if sel_anim is not None:
            self._draw_selection_rect(p, sel_anim)
            p.resetTransform()
            self._draw_gizmo(p, sel_anim)
        p.end()

    def _draw_selection_rect(self, p: QPainter, a: Animation):
        cam = self.camera
        idxs = self.editor.outline_indices(a)
        if not idxs:
            return
        x0 = y0 = 1e30
        x1 = y1 = -1e30
        for i in idxs:
            if i < 0 or i >= len(a.frames):
                continue
            x, y, w, h = gifproc.frame_world_rect(a, i)
            x0, y0 = min(x0, x), min(y0, y)
            x1, y1 = max(x1, x + w), max(y1, y + h)
        if x0 > x1:
            return
        pen = QPen(_SEL)
        pen.setWidthF(1.5 / cam.zoom)
        pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(x0, y0, x1 - x0, y1 - y0))

    def _draw_gizmo(self, p: QPainter, a: Animation):
        # transform gizmo at the anchor, constant screen size
        ax, ay = self.camera.w2s(a.pos_x, a.pos_y, self.width(), self.height())
        arm = 26.0  # screen px
        p.setPen(QPen(_SEL, 2))
        p.setBrush(QBrush(_SEL))
        p.drawLine(QPointF(ax, ay), QPointF(ax + arm, ay))
        p.drawEllipse(QPointF(ax + arm, ay), 5, 5)
        p.drawLine(QPointF(ax, ay), QPointF(ax, ay + arm))
        p.drawEllipse(QPointF(ax, ay + arm), 5, 5)
        p.drawRect(QRectF(ax - 5, ay - 5, 10, 10))

    def _ghost_indices(self, a: Animation) -> list[int]:
        """Onion-skin frame indices around the playhead.

        Previous ghost is always shown when onion skinning is on; the next
        ghost is independent. Loops wrap around; non-looping animations
        show no ghost past the ends.
        """
        out = []
        n = len(a.frames)
        cur = int(a.cur_frame)
        if n < 2:
            return out
        if self.editor.onion_skin:
            p = cur - 1
            if p < 0:
                p = n - 1 if a.loop else -1
            if p >= 0:
                out.append(p)
        if self.editor.ghost_next:
            q = cur + 1
            if q >= n:
                q = 0 if a.loop else -1
            if 0 <= q < n:
                out.append(q)
        return out

    def _draw_anim(self, p: QPainter, ed: "EditorTab", a: Animation,
                   primary_only: bool, alpha: float):
        idxs = ed.draw_indices(a)
        cam = self.camera
        for i in idxs:
            if i < 0 or i >= len(a.frames):
                continue
            img = self._frame_image(a, i)
            if img.isNull():
                continue
            x, y = gifproc.frame_sprite_topleft(a, i)
            target = QRectF(x, y, img.width(), img.height())
            if primary_only:
                p.setOpacity(alpha)
                p.drawImage(target, img)
                p.setOpacity(1.0)
            else:
                # selected frames solid, unselected frames of the same
                # animation faint - the whole stack stays visible
                lit = i in ed.frame_sel or i == a.cur_frame
                # onion-skin ghosts under the playhead frame - visual
                # reference only, never hit-tested or selectable
                if i == a.cur_frame:
                    for gidx in self._ghost_indices(a):
                        gimg = self._frame_image(a, gidx)
                        if gimg.isNull():
                            continue
                        gx, gy = gifproc.frame_sprite_topleft(a, gidx)
                        p.setOpacity(ed.GHOST_ALPHA)
                        p.drawImage(QRectF(gx, gy, gimg.width(), gimg.height()), gimg)
                        p.setOpacity(1.0)
                if not lit:
                    p.setOpacity(0.22)
                p.drawImage(target, img)
                if not lit:
                    p.setOpacity(1.0)

    # ------------------------------------------------------------- input --
    def _gizmo_hit(self, sx: float, sy: float, a: Animation) -> str | None:
        ax, ay = self.camera.w2s(a.pos_x, a.pos_y, self.width(), self.height())
        arm = 26.0
        if (sx - (ax + arm)) ** 2 + (sy - ay) ** 2 <= 64:
            return "x"
        if (sx - ax) ** 2 + (sy - (ay + arm)) ** 2 <= 64:
            return "y"
        if abs(sx - ax) <= 9 and abs(sy - ay) <= 9:
            return "center"
        return None

    def _anim_at(self, wx: float, wy: float):
        """Returns (Animation, frame_index) of the topmost sprite hit."""
        for a in reversed(self.editor.animations):
            for i in self.editor.draw_indices(a):
                if i < 0 or i >= len(a.frames):
                    continue
                # hit-test the sprite's own rect (canvas is shared)
                sx, sy = gifproc.frame_sprite_topleft(a, i)
                iw, ih = a.frames[i].image.size
                if sx <= wx <= sx + iw and sy <= wy <= sy + ih:
                    return a, i
        return None, -1

    def mousePressEvent(self, ev):
        ed = self.editor
        if ev.button() == Qt.MiddleButton or (ev.button() == Qt.LeftButton and self._space_pan):
            self._pan = (ev.position().x(), ev.position().y())
            return
        if ev.button() != Qt.LeftButton:
            return
        pos = ev.position()
        sx, sy = pos.x(), pos.y()
        a = ed.current_anim()
        if a is not None:
            g = self._gizmo_hit(sx, sy, a)
            if g:
                self._drag = {"kind": "gizmo-" + g, "anim": a,
                              "start": (a.pos_x, a.pos_y),
                              "moved": False}
                return
        hit, hit_idx = self._anim_at(*self.camera.s2w(sx, sy, self.width(), self.height()))
        if hit is not None:
            ed.select_animation(hit)
            a = hit
            if ed.move_mode == "frames":
                # clicking a frame in frame-edit mode selects just that frame
                a.cur_frame = hit_idx
                ed.frame_sel = {hit_idx}
                ed.refresh_props()
                ed.timeline.update()
                ed.revision += 1
            if ed.move_mode == "frames" and ed.frame_sel:
                snap = {int(i): (a.frames[int(i)].user_dx, a.frames[int(i)].user_dy)
                        for i in ed.frame_sel if int(i) < len(a.frames)}
                self._drag = {"kind": "frames", "anim": a, "sel": set(ed.frame_sel),
                              "start": self.camera.s2w(sx, sy, self.width(), self.height()),
                              "snap": snap, "moved": False}
            else:
                self._drag = {"kind": "anim", "anim": a,
                              "start": (a.pos_x, a.pos_y),
                              "moved": False}
        # clicking empty space does nothing (no marquee)

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        if self._pan is not None:
            lx, ly = self._pan
            self.camera.pan_pixels(pos.x() - lx, pos.y() - ly)
            self._pan = (pos.x(), pos.y())
            self.update()
            return
        d = self._drag
        if d is None:
            return
        ed = self.editor
        if d["kind"].startswith("gizmo") or d["kind"] == "anim":
            mode = d["kind"].replace("gizmo-", "") if d["kind"].startswith("gizmo") else "both"
            # world delta of the cursor since drag start isn't stored for
            # gizmo/anim - track via last position instead
            if "last" not in d:
                d["last"] = self.camera.s2w(pos.x(), pos.y(), self.width(), self.height())
                return
            wx, wy = self.camera.s2w(pos.x(), pos.y(), self.width(), self.height())
            dx, dy = wx - d["last"][0], wy - d["last"][1]
            d["last"] = (wx, wy)
            a = d["anim"]
            if mode in ("x", "both"):
                a.pos_x += dx
            if mode in ("y", "both"):
                a.pos_y += dy
            d["moved"] = True
            ed.revision += 1
            ed.refresh_props()
            self.update()
        elif d["kind"] == "frames":
            wx, wy = self.camera.s2w(pos.x(), pos.y(), self.width(), self.height())
            dx, dy = wx - d["start"][0], wy - d["start"][1]
            a = d["anim"]
            for i, (odx, ody) in d["snap"].items():
                i = int(i)
                a.frames[i].user_dx = odx + dx
                a.frames[i].user_dy = ody + dy
            gifproc.align(a)
            d["moved"] = True
            ed.revision += 1
            ed.refresh_props()
            self.update()

    def mouseReleaseEvent(self, ev):
        if self._pan is not None:
            self._pan = None
            return
        if ev.button() != Qt.LeftButton:
            return
        d = self._drag
        self._drag = None
        if d is None or not d.get("moved"):
            return
        ed = self.editor
        a = d["anim"]
        if d["kind"] == "frames":
            new = {i: (a.frames[i].user_dx, a.frames[i].user_dy) for i in d["snap"]}
            ed.push_cmd(f"move {len(new)} frame(s)",
                        lambda: ed._restore_frame_offsets(a, d["snap"]),
                        lambda: ed._restore_frame_offsets(a, new))
        else:
            mode = d["kind"].replace("gizmo-", "") if d["kind"].startswith("gizmo") else "both"
            old = d["start"]
            newp = (a.pos_x, a.pos_y)
            def restore(pos):
                if mode in ("x", "both"):
                    a.pos_x = pos[0]
                if mode in ("y", "both"):
                    a.pos_y = pos[1]
            ed.push_cmd("move sprite", lambda: restore(old), lambda: restore(newp))
        ed.refresh_all()

    def wheelEvent(self, ev):
        factor = 1.12 if ev.angleDelta().y() > 0 else 1.0 / 1.12
        pos = ev.position()
        self.camera.zoom_at(factor, (pos.x(), pos.y()), self.width(), self.height())
        self.editor.refresh_props()
        self.update()

    def mouseDoubleClickEvent(self, ev):
        pos = ev.position()
        hit, _hi = self._anim_at(*self.camera.s2w(pos.x(), pos.y(),
                                                  self.width(), self.height()))
        if hit is None:
            self.camera.reset()
            self.editor.refresh_props()
            self.update()

    def keyPressEvent(self, ev):
        ed = self.editor
        a = ed.current_anim()
        key = ev.key()
        if key in (Qt.Key_Plus, Qt.Key_Equal):
            self.camera.zoom_center(1.25, self.width(), self.height())
        elif key in (Qt.Key_Minus, Qt.Key_Underscore):
            self.camera.zoom_center(1.0 / 1.25, self.width(), self.height())
        elif key == Qt.Key_0:
            self.camera.reset()
        elif key == Qt.Key_Space and a is not None:
            ed.toggle_play()
        elif key in (Qt.Key_BracketLeft, Qt.Key_BracketRight) and ed.animations:
            d = -1 if key == Qt.Key_BracketLeft else 1
            ed.sel = (ed.sel + d) % len(ed.animations)
            ed.select_animation(ed.animations[ed.sel])
        elif a is not None and key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            step = 8.0 if ev.modifiers() & Qt.ShiftModifier else 1.0
            dx = dy = 0.0
            if key == Qt.Key_Left: dx = -step
            elif key == Qt.Key_Right: dx = step
            elif key == Qt.Key_Up: dy = -step
            else: dy = step
            old = (a.pos_x, a.pos_y)
            a.pos_x += dx
            a.pos_y += dy
            ed.push_cmd("nudge sprite",
                        lambda: setattr(a, "pos_x", old[0]) or setattr(a, "pos_y", old[1]),
                        lambda: setattr(a, "pos_x", old[0] + dx) or setattr(a, "pos_y", old[1] + dy))
            ed.refresh_props()
        else:
            return
        ed.refresh_props()
        self.update()

    def keyReleaseEvent(self, ev):
        pass


# ---------------------------------------------------------------- timeline --

class Timeline(QWidget):
    """Bottom strip: frame thumbnails + transport for the selected GIF."""

    CELL = 72
    LABEL_H = 18

    def __init__(self, editor: "EditorTab"):
        super().__init__()
        self.editor = editor
        self._sel_anchor = 0
        self.setMinimumHeight(120)

    # ------------------------------------------------------------ paint --
    def paintEvent(self, _ev):
        ed = self.editor
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(22, 22, 30))
        a = ed.current_anim()
        if a is None or not a.frames:
            p.setPen(QColor(120, 120, 140))
            p.drawText(self.rect(), Qt.AlignCenter, "import animations to edit")
            p.end()
            return
        n = len(a.frames)
        # centre the strip horizontally
        total = n * self.CELL
        x0 = max(8, (self.width() - total) // 2)
        y0 = 8
        for i in range(n):
            x = x0 + i * self.CELL
            sel = i in ed.frame_sel
            cur = i == a.cur_frame
            if sel:
                p.fillRect(x + 1, y0 + 1, self.CELL - 2, self.CELL - 2 + self.LABEL_H,
                           QColor(50, 90, 150))
            if cur:
                p.setPen(QPen(_SEL, 2))
                p.drawRect(x + 1, y0 + 1, self.CELL - 2, self.CELL - 2 + self.LABEL_H)
            img = ed.viewport._frame_image(a, i)
            if not img.isNull():
                thumb = img.scaled(self.CELL - 12, self.CELL - 12,
                                   Qt.KeepAspectRatio, Qt.SmoothTransformation)
                p.drawImage(QRectF(x + 6 + (self.CELL - 12 - thumb.width()) / 2,
                                   y0 + 6 + (self.CELL - 12 - thumb.height()) / 2,
                                   thumb.width(), thumb.height()), thumb)
            p.setPen(QColor(200, 200, 210))
            p.drawText(QRectF(x, y0 + self.CELL - 2, self.CELL, self.LABEL_H),
                       Qt.AlignHCenter | Qt.AlignTop, str(i + 1))
            f = a.frames[i]
            p.setPen(QColor(140, 140, 160))
            p.drawText(QRectF(x, y0 + self.CELL + self.LABEL_H - 6, self.CELL, self.LABEL_H),
                       Qt.AlignHCenter | Qt.AlignTop, f"{f.duration_ms}ms")
        p.end()

    # ------------------------------------------------------------- input --
    def _cell_at(self, x: int) -> int:
        ed = self.editor
        a = ed.current_anim()
        if a is None:
            return -1
        total = len(a.frames) * self.CELL
        x0 = max(8, (self.width() - total) // 2)
        # ev.position() is float in Qt6 - // yields float; indices must be int
        i = int((x - x0) // self.CELL)
        return i if 0 <= i < len(a.frames) else -1

    def mousePressEvent(self, ev):
        ed = self.editor
        a = ed.current_anim()
        if a is None:
            return
        i = self._cell_at(ev.position().x())
        if i < 0:
            return
        mods = ev.modifiers()
        if mods & Qt.ControlModifier:
            if i in ed.frame_sel:
                ed.frame_sel.discard(i)
            else:
                ed.frame_sel.add(i)
            if not ed.frame_sel:
                ed.frame_sel.add(a.cur_frame)
        elif mods & Qt.ShiftModifier:
            lo, hi = sorted((self._sel_anchor, i))
            ed.frame_sel = set(range(lo, hi + 1))
        else:
            ed.frame_sel = {i}
            self._sel_anchor = i
        a.cur_frame = i
        ed.revision += 1
        ed.refresh_props()
        self.update()
        ed.viewport.update()

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(400, 120)


# -------------------------------------------------------------- editor tab --

class EditorTab(QWidget):
    """Workspace editor: viewport + timeline + properties + undo."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.animations: list[Animation] = []
        self.sel = -1
        self.frame_sel: set[int] = set()
        self.origin: tuple[float, float] = (0.0, 0.0)
        self.revision = 0
        self.char_name = "character"
        # view options
        self.show_grid = True
        self.show_origin = True
        self.show_anchors = True
        self.move_mode = "anim"          # "anim" (Move GIF) | "frames" (Move Frame)
        self.onion_skin = False          # previous-frame ghost, fixed 50%
        self.ghost_next = False          # next-frame ghost toggle
        self.GHOST_ALPHA = 0.5
        self.speed = 1.0
        self._undo: list[_LambdaCmd] = []
        self._redo: list[_LambdaCmd] = []
        self._elapsed = QElapsedTimer()
        self._build()
        self._play_timer = QTimer(self)
        self._play_timer.timeout.connect(self._tick)

    # ------------------------------------------------------------- build --
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        # toolbar: project + character name + undo
        tb = QHBoxLayout()
        self.char_edit = QLineEdit(self.char_name)
        self.char_edit.setMaximumWidth(160)
        self.char_edit.setPlaceholderText("character name")
        self.char_edit.editingFinished.connect(self._char_changed)
        openb = QPushButton("Open project…")
        openb.clicked.connect(self._open_project)
        saveb = QPushButton("Save project…")
        saveb.clicked.connect(self._save_project)
        undob = QPushButton("Undo")
        undob.clicked.connect(self.undo)
        redob = QPushButton("Redo")
        redob.clicked.connect(self.redo)
        for w in (openb, saveb, undob, redob):
            tb.addWidget(w)
        tb.addSpacing(12)
        tb.addWidget(QLabel("Char:"))
        tb.addWidget(self.char_edit)
        tb.addStretch(1)
        self.status = QLabel("")
        tb.addWidget(self.status)
        root.addLayout(tb)

        # main split: workspace | properties
        self.viewport = Viewport(self)
        self.timeline = Timeline(self)
        self.props = self._build_props()

        left = QVBoxLayout()
        left.setSpacing(0)
        left.addWidget(self.viewport, 1)
        left.addWidget(self.timeline)
        leftw = QWidget()
        leftw.setLayout(left)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(leftw)
        split.addWidget(self.props)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setSizes([820, 280])
        root.addWidget(split, 1)

        # transport controls live in a row above the timeline
        trans = QHBoxLayout()
        for label, fn in [("|<", lambda: self._step_home()), ("<", lambda: self._step(-1)),
                          ("Play", self.toggle_play), (">", lambda: self._step(1)),
                          (">|", lambda: self._step_end())]:
            b = QPushButton(label)
            if label == "Play":
                b.setCheckable(True)
                b.toggled.connect(lambda on, btn=b: self._set_playing(on, btn))
            else:
                b.clicked.connect(fn)
            b.setFixedWidth(40)
            trans.addWidget(b)
        self.scrub = QSlider(Qt.Horizontal)
        self.scrub.valueChanged.connect(self._scrub)
        trans.addWidget(self.scrub, 1)
        self.frame_label = QLabel("0/0")
        trans.addWidget(self.frame_label)
        trans.addWidget(QLabel("Speed"))
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0.1, 8.0)
        self.speed_spin.setSingleStep(0.25)
        self.speed_spin.setValue(1.0)
        self.speed_spin.valueChanged.connect(lambda v: setattr(self, "speed", v))
        trans.addWidget(self.speed_spin)
        # transport row sits between viewport and timeline
        left.insertLayout(1, trans)

    def _build_props(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)

        # ---- animation section ----
        ga = QGroupBox("Animation")
        fa = QFormLayout(ga)
        self.name_edit = QLineEdit()
        self.prefix_edit = QLineEdit()
        self.fps_spin = QDoubleSpinBox()
        self.fps_spin.setRange(0.1, 120)
        self.fps_spin.setSingleStep(0.5)
        self.loop_check = QCheckBox("loop")
        self.anim_ox = QDoubleSpinBox()
        self.anim_oy = QDoubleSpinBox()
        self.anim_px = QDoubleSpinBox()
        self.anim_py = QDoubleSpinBox()
        for s in (self.anim_ox, self.anim_oy, self.anim_px, self.anim_py):
            s.setRange(-100000, 100000)
            s.setSingleStep(1)
            s.setDecimals(1)
        fa.addRow("Name", self.name_edit)
        fa.addRow("Prefix", self.prefix_edit)
        fa.addRow("FPS", self.fps_spin)
        fa.addRow("", self.loop_check)
        fa.addRow("Align offset X", self.anim_ox)
        fa.addRow("Align offset Y", self.anim_oy)
        fa.addRow("Position X", self.anim_px)
        fa.addRow("Position Y", self.anim_py)
        brow = QHBoxLayout()
        rb = QPushButton("Reset pos")
        rb.clicked.connect(self._reset_anim_pos)
        cb = QPushButton("Copy pos → all")
        cb.clicked.connect(self._copy_pos_all)
        ab = QPushButton("Stabilize…")
        ab.clicked.connect(self._align_assistant)
        for b in (rb, cb, ab):
            brow.addWidget(b)
        fa.addRow(brow)
        lay.addWidget(ga)

        # ---- frame section ----
        gf = QGroupBox("Frame")
        ff = QFormLayout(gf)
        self.frame_info = QLabel("-")
        self.eff_label = QLabel("-")
        self.anchor_label = QLabel("-")
        self.fdx = QDoubleSpinBox()
        self.fdy = QDoubleSpinBox()
        self.fdur = QDoubleSpinBox()
        self.fdur.setRange(1, 60000)
        self.fdur.setSuffix(" ms")
        for s in (self.fdx, self.fdy):
            s.setRange(-5000, 5000)
            s.setSingleStep(0.5)
            s.setDecimals(2)
        ff.addRow("Selection", self.frame_info)
        ff.addRow("Effective X/Y", self.eff_label)
        ff.addRow("Anchor", self.anchor_label)
        ff.addRow("Offset X", self.fdx)
        ff.addRow("Offset Y", self.fdy)
        ff.addRow("Duration", self.fdur)
        frow = QHBoxLayout()
        fr = QPushButton("Reset frame")
        fr.clicked.connect(self._reset_frame)
        fc = QPushButton("Copy → sel")
        fc.clicked.connect(self._copy_frame_to_sel)
        fa_all = QPushButton("→ all frames")
        fa_all.clicked.connect(self._copy_frame_to_all)
        for b in (fr, fc, fa_all):
            frow.addWidget(b)
        ff.addRow(frow)
        lay.addWidget(gf)

        # ---- view section ----
        gv = QGroupBox("View")
        fv = QFormLayout(gv)
        self.zoom_label = QLabel("100%")
        self.grid_check = QCheckBox("grid")
        self.grid_check.setChecked(True)
        self.origin_check = QCheckBox("character origin")
        self.origin_check.setChecked(True)
        self.anchors_check = QCheckBox("anchors")
        self.anchors_check.setChecked(True)
        self.onion_check = QCheckBox("onion skin (prev frame)")
        self.next_ghost_check = QCheckBox("next frame ghost")
        self.ox_origin = QDoubleSpinBox()
        self.oy_origin = QDoubleSpinBox()
        for s in (self.ox_origin, self.oy_origin):
            s.setRange(-100000, 100000)
            s.setSingleStep(1)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Move GIF", "Move Frame"])
        fv.addRow("Zoom", self.zoom_label)
        fv.addRow(self.grid_check)
        fv.addRow(self.origin_check)
        fv.addRow(self.anchors_check)
        fv.addRow(self.onion_check)
        fv.addRow(self.next_ghost_check)
        fv.addRow("origin X", self.ox_origin)
        fv.addRow("origin Y", self.oy_origin)
        fv.addRow(self.mode_combo)
        lay.addWidget(gv)
        lay.addStretch(1)

        # wire view options
        self.grid_check.stateChanged.connect(lambda s: setattr(self, "show_grid", bool(s)) or self.viewport.update())
        self.origin_check.stateChanged.connect(lambda s: setattr(self, "show_origin", bool(s)) or self.viewport.update())
        self.anchors_check.stateChanged.connect(lambda s: setattr(self, "show_anchors", bool(s)) or self.viewport.update())
        self.onion_check.stateChanged.connect(self._onion_toggled)
        self.next_ghost_check.stateChanged.connect(self._next_ghost_toggled)
        self.ox_origin.valueChanged.connect(lambda v: self._set_origin(v, self.origin[1]))
        self.oy_origin.valueChanged.connect(lambda v: self._set_origin(self.origin[0], v))
        self.mode_combo.currentIndexChanged.connect(
            lambda i: setattr(self, "move_mode", "frames" if i else "anim"))
        # animation fields commit on editingFinished (undoable)
        for fld in (self.name_edit, self.prefix_edit, self.fps_spin,
                    self.anim_ox, self.anim_oy, self.anim_px, self.anim_py):
            fld.editingFinished.connect(self._commit_anim_form)
        self.loop_check.stateChanged.connect(lambda _s: self._commit_anim_form())
        # frame fields commit on editingFinished (undoable via model compare)
        self.fdx.editingFinished.connect(self._commit_frame_form)
        self.fdy.editingFinished.connect(self._commit_frame_form)
        self.fdur.editingFinished.connect(self._commit_frame_form)
        return w

    # ------------------------------------------------------------ model --
    def set_animations(self, animations: list[Animation]):
        self.animations = animations
        self.sel = 0 if animations else -1
        self.frame_sel = set()
        self.refresh_all()

    def current_anim(self) -> Animation | None:
        if 0 <= self.sel < len(self.animations):
            a = self.animations[self.sel]
            # indices must be ints - a float here once crashed every paint
            if a.frames:
                a.cur_frame = int(a.cur_frame) % len(a.frames)
            return a
        return None

    def select_animation(self, a: Animation):
        try:
            self.sel = self.animations.index(a)
        except ValueError:
            return
        self.frame_sel = {a.cur_frame} if a.frames else set()
        self.revision += 1
        self.refresh_props()
        self.timeline.update()
        self.viewport.update()

    def draw_indices(self, a: Animation) -> list[int]:
        """Frame indices the viewport should draw for `a`.

        In frame-edit mode the WHOLE animation stays visible - selected
        frames draw solid, the rest draw faint - so you can always see
        what you're aligning against.
        """
        if a.frames and a is self.current_anim() and self.move_mode == "frames":
            return list(range(len(a.frames)))
        return [int(a.cur_frame)] if a.frames else []

    def outline_indices(self, a: Animation) -> list[int]:
        """Frames that get the selection outline (selected + playhead)."""
        if a is self.current_anim() and self.move_mode == "frames":
            sel = {int(i) for i in self.frame_sel} | {int(a.cur_frame)}
            return sorted(i for i in sel if 0 <= i < len(a.frames))
        return [int(a.cur_frame)] if a.frames else []

    # ------------------------------------------------------------- undo --
    def push_cmd(self, text: str, undo, redo):
        cmd = _LambdaCmd(text, undo, redo)
        self._undo.append(cmd)
        self._redo.clear()
        cmd.redo()
        self.refresh_all()

    def undo(self):
        if not self._undo:
            return
        cmd = self._undo.pop()
        cmd.undo()
        self._redo.append(cmd)
        self.refresh_all()

    def redo(self):
        if not self._redo:
            return
        cmd = self._redo.pop()
        cmd.redo()
        self._undo.append(cmd)
        self.refresh_all()

    def _restore_frame_offsets(self, a: Animation, snap: dict):
        changed = False
        for i, (dx, dy) in snap.items():
            i = int(i)
            if 0 <= i < len(a.frames):
                a.frames[i].user_dx, a.frames[i].user_dy = dx, dy
                changed = True
        if changed:
            gifproc.align(a)
            self.revision += 1
            self.refresh_props()
            self.timeline.update()
            self.viewport.update()

    # --------------------------------------------------------- animation --
    def _commit_anim_form(self):
        a = self.current_anim()
        if a is None:
            return
        # position spins commit separately (they are the workspace transform)
        new_pos = (self.anim_px.value(), self.anim_py.value())
        old_pos = (a.pos_x, a.pos_y)
        if new_pos != old_pos:
            def apply_pos(p):
                a.pos_x, a.pos_y = p
                self.revision += 1
                self.refresh_props()
                self.viewport.update()
            self.push_cmd("move animation",
                          lambda: apply_pos(old_pos), lambda: apply_pos(new_pos))
        old = (a.name, a.prefix, a.fps, a.loop, a.offset_x, a.offset_y)
        new = (self.name_edit.text() or a.name, self.prefix_edit.text(),
               self.fps_spin.value(), self.loop_check.isChecked(),
               self.anim_ox.value(), self.anim_oy.value())
        if new == old:
            return
        def apply(vals):
            a.name, a.prefix, a.fps, a.loop, a.offset_x, a.offset_y = vals
            gifproc.align(a)
            self.revision += 1
            self.refresh_props()
            self.timeline.update()
            self.viewport.update()
        self.push_cmd("edit animation", lambda: apply(old), lambda: apply(new))

    def _commit_frame_form(self):
        a = self.current_anim()
        if a is None or not self.frame_sel:
            return
        idxs = sorted(int(i) for i in self.frame_sel if int(i) < len(a.frames))
        if not idxs:
            return
        # snapshot old values, apply new where different
        old = {}
        new = {}
        for i in idxs:
            f = a.frames[i]
            o = (f.user_dx, f.user_dy, f.duration_ms)
            n = (self.fdx.value(), self.fdy.value(), int(self.fdur.value()))
            if o != n:
                old[i] = o
                new[i] = n
        if not old:
            return
        def apply(snap):
            for i, (dx, dy, dur) in snap.items():
                a.frames[i].user_dx, a.frames[i].user_dy = dx, dy
                a.frames[i].duration_ms = dur
            gifproc.align(a)
            self.revision += 1
            self.refresh_props()
            self.timeline.update()
            self.viewport.update()
        self.push_cmd("edit frame(s)", lambda: apply(old), lambda: apply(new))

    def _reset_anim_pos(self):
        a = self.current_anim()
        if a is None:
            return
        old = (a.pos_x, a.pos_y)
        def apply(p):
            a.pos_x, a.pos_y = p
            self.revision += 1
            self.refresh_props()
            self.viewport.update()
        self.push_cmd("reset position", lambda: apply(old), lambda: apply((0.0, 0.0)))

    def _copy_pos_all(self):
        a = self.current_anim()
        if a is None:
            return
        pos = (a.pos_x, a.pos_y)
        olds = [(x.pos_x, x.pos_y) for x in self.animations]
        def apply(snap):
            for x, p in zip(self.animations, snap):
                x.pos_x, x.pos_y = p
            self.revision += 1
            self.refresh_props()
            self.viewport.update()
        new = [pos] * len(self.animations)
        self.push_cmd("copy position to all",
                      lambda: apply(olds), lambda: apply(new))

    def _reset_frame(self):
        a = self.current_anim()
        if a is None or not self.frame_sel:
            return
        idxs = [int(i) for i in self.frame_sel if int(i) < len(a.frames)]
        old = {i: (a.frames[i].user_dx, a.frames[i].user_dy) for i in idxs}
        new = {i: (0.0, 0.0) for i in idxs}
        self._restore_frame_offsets(a, new)
        self.push_cmd("reset frame offsets",
                      lambda: self._restore_frame_offsets(a, old),
                      lambda: self._restore_frame_offsets(a, new))

    def _copy_frame_to_sel(self):
        a = self.current_anim()
        if a is None or a.cur_frame >= len(a.frames):
            return
        src = a.frames[a.cur_frame]
        idxs = [int(i) for i in self.frame_sel
                if int(i) < len(a.frames) and int(i) != a.cur_frame]
        if not idxs:
            return
        old = {i: (a.frames[i].user_dx, a.frames[i].user_dy) for i in idxs}
        new = {i: (src.user_dx, src.user_dy) for i in idxs}
        self._restore_frame_offsets(a, new)
        self.push_cmd("copy frame offset",
                      lambda: self._restore_frame_offsets(a, old),
                      lambda: self._restore_frame_offsets(a, new))

    def _copy_frame_to_all(self):
        a = self.current_anim()
        if a is None or a.cur_frame >= len(a.frames):
            return
        src = a.frames[a.cur_frame]
        old = {i: (f.user_dx, f.user_dy) for i, f in enumerate(a.frames)}
        new = {i: (src.user_dx, src.user_dy) for i in range(len(a.frames))}
        self._restore_frame_offsets(a, new)
        self.push_cmd("apply frame offset to all",
                      lambda: self._restore_frame_offsets(a, old),
                      lambda: self._restore_frame_offsets(a, new))

    # -------------------------------------------------------- view opts --
    def _onion_toggled(self, on):
        self.onion_skin = bool(on)
        self.viewport.update()

    def _next_ghost_toggled(self, on):
        self.ghost_next = bool(on)
        self.viewport.update()

    def _set_origin(self, x, y):
        old = self.origin
        self.origin = (float(x), float(y))
        def apply(o):
            self.origin = o
            self.viewport.update()
        self.push_cmd("move origin", lambda: apply(old), lambda: apply(self.origin))

    # --------------------------------------------------------- playback --
    def toggle_play(self):
        if getattr(self, "_playing", False):
            self._set_playing(False)
        else:
            self._set_playing(True)

    def _set_playing(self, on: bool, _btn=None):
        a = self.current_anim()
        if on and a is not None:
            self._play_timer.start(33)
            self._elapsed.restart()
            self._playing = True
        else:
            self._play_timer.stop()
            self._playing = False

    _playing = False

    def _tick(self):
        dt = self._elapsed.restart()
        for a in self.animations:
            if not a.frames:
                continue
            # accumulate real time, advance by per-frame durations
            acc = getattr(a, "_acc", 0.0) + dt * self.speed
            while a.frames:
                dur = max(1, a.frames[a.cur_frame].duration_ms)
                if acc < dur:
                    break
                acc -= dur
                a.cur_frame = int((a.cur_frame + 1) % len(a.frames))
                if not a.loop and a.cur_frame == 0:
                    break
            a._acc = acc
        self.refresh_props()
        self.timeline.update()
        self.viewport.update()

    def _step(self, d: int):
        a = self.current_anim()
        if a is None or not a.frames:
            return
        a.cur_frame = (a.cur_frame + d) % len(a.frames)
        self.frame_sel = {a.cur_frame}
        self.revision += 1
        self.refresh_props()
        self.timeline.update()
        self.viewport.update()

    def _step_home(self):
        a = self.current_anim()
        if a is None or not a.frames:
            return
        a.cur_frame = 0
        self.frame_sel = {0}
        self.refresh_all()

    def _step_end(self):
        a = self.current_anim()
        if a is None or not a.frames:
            return
        a.cur_frame = len(a.frames) - 1
        self.frame_sel = {a.cur_frame}
        self.refresh_all()

    def _scrub(self, v: int):
        a = self.current_anim()
        if a is None or not a.frames:
            return
        a.cur_frame = min(v, len(a.frames) - 1)
        self.frame_sel = {a.cur_frame}
        self.refresh_props()
        self.timeline.update()
        self.viewport.update()

    # --------------------------------------------------------- refresh --
    def refresh_props(self):
        a = self.current_anim()
        for w in (self.name_edit, self.prefix_edit, self.fps_spin, self.loop_check,
                  self.anim_ox, self.anim_oy, self.anim_px, self.anim_py,
                  self.fdx, self.fdy, self.fdur):
            w.blockSignals(True)
        if a is None:
            for w in (self.name_edit, self.prefix_edit):
                w.clear()
            for w in (self.fps_spin, self.anim_ox, self.anim_oy,
                      self.anim_px, self.anim_py, self.fdx, self.fdy):
                w.setValue(0)
            self.fdur.setValue(100)
            self.loop_check.setChecked(True)
            self.frame_info.setText("-")
            self.eff_label.setText("-")
            self.anchor_label.setText("-")
            self.scrub.setRange(0, 0)
            self.frame_label.setText("0/0")
            self.zoom_label.setText(f"{self.viewport.camera.zoom_pct}%")
        else:
            self.eff_label.setText("-")
            self.anchor_label.setText(
                f"({a.anchor[0]:.1f}, {a.anchor[1]:.1f})")
            if a.cur_frame < len(a.frames):
                ex, ey = gifproc.frame_sprite_topleft(a, a.cur_frame)
                self.eff_label.setText(f"({ex:.1f}, {ey:.1f})")
            self.name_edit.setText(a.name)
            self.prefix_edit.setText(a.prefix)
            self.fps_spin.setValue(a.fps)
            self.loop_check.setChecked(a.loop)
            self.anim_ox.setValue(a.offset_x)
            self.anim_oy.setValue(a.offset_y)
            self.anim_px.setValue(a.pos_x)
            self.anim_py.setValue(a.pos_y)
            self._fill_frame_fields(a)
            n = len(a.frames)
            self.scrub.blockSignals(True)
            self.scrub.setRange(0, max(0, n - 1))
            self.scrub.setValue(min(a.cur_frame, max(0, n - 1)))
            self.scrub.blockSignals(False)
            self.frame_label.setText(f"{a.cur_frame + 1}/{n}")
            self.zoom_label.setText(f"{self.viewport.camera.zoom_pct}%")
        for w in (self.name_edit, self.prefix_edit, self.fps_spin, self.loop_check,
                  self.anim_ox, self.anim_oy, self.anim_px, self.anim_py,
                  self.fdx, self.fdy, self.fdur):
            w.blockSignals(False)
        # origin spins
        self.ox_origin.blockSignals(True)
        self.oy_origin.blockSignals(True)
        self.ox_origin.setValue(self.origin[0])
        self.oy_origin.setValue(self.origin[1])
        self.ox_origin.blockSignals(False)
        self.oy_origin.blockSignals(False)

    def _fill_frame_fields(self, a: Animation):
        idxs = [int(i) for i in self.frame_sel if int(i) < len(a.frames)]
        if not idxs:
            self.frame_info.setText("no frame")
            return
        if len(idxs) == 1:
            f = a.frames[idxs[0]]
            self.frame_info.setText(f"frame {idxs[0] + 1} / {len(a.frames)}")
            self.fdx.setValue(f.user_dx)
            self.fdy.setValue(f.user_dy)
            self.fdur.setValue(f.duration_ms)
        else:
            # show aggregate: only enable editing if all share values
            dxs = {round(a.frames[i].user_dx, 3) for i in idxs}
            dys = {round(a.frames[i].user_dy, 3) for i in idxs}
            durs = {a.frames[i].duration_ms for i in idxs}
            self.frame_info.setText(f"{len(idxs)} frames selected")
            self.fdx.setEnabled(len(dxs) == 1)
            self.fdy.setEnabled(len(dys) == 1)
            self.fdur.setEnabled(len(durs) == 1)
            if len(dxs) == 1:
                self.fdx.setValue(next(iter(dxs)))
            if len(dys) == 1:
                self.fdy.setValue(next(iter(dys)))
            if len(durs) == 1:
                self.fdur.setValue(next(iter(durs)))
        if len(idxs) == 1:
            self.fdx.setEnabled(True)
            self.fdy.setEnabled(True)
            self.fdur.setEnabled(True)

    def refresh_all(self):
        self.refresh_props()
        self.timeline.update()
        self.viewport.update()

    # ------------------------------------------------------------ project --
    def _char_changed(self):
        self.char_name = self.char_edit.text().strip() or "character"

    def _open_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open sprite project", "", "RCHR project (*.rchr)")
        if not path:
            return
        self.window().open_project(path)

    def _save_project(self):
        self._char_changed()
        path, _ = QFileDialog.getSaveFileName(
            self, "Save sprite project", "", "RCHR project (*.rchr)")
        if not path:
            return
        try:
            keep = QMessageBox.question(
                self, "Keep source GIFs?",
                "Embed the original GIF/WebP files in the project?\n"
                "(larger file, but allows re-alignment later)",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes
            res = project.save_project(path, self.animations,
                                       self.char_name, self.origin, keep_source=keep)
            self.status.setText(
                f"saved {res['entries']} entries, {res['stored_bytes']} bytes")
        except Exception as e:  # noqa: BLE001
            self.status.setText(f"save failed: {e}")

    # --------------------------------------------------- align assistant --
    def _align_assistant(self):
        a = self.current_anim()
        if a is None or len(a.frames) < 2:
            return
        gifproc.align(a)
        sug = gifproc.suggest_stabilize(a, threshold=2.0)
        dlg = _AlignDialog(self, a, sug)
        dlg.exec()


class _AlignDialog(QDialog):
    """Preview/confirm UI for automatic stabilisation suggestions."""

    def __init__(self, editor: EditorTab, anim: Animation, sug: dict):
        super().__init__(editor)
        self.editor = editor
        self.anim = anim
        self.sug = sug
        self._backup = None
        self.setWindowTitle("Stabilize frames")
        lay = QVBoxLayout(self)
        if not sug:
            lay.addWidget(QLabel("No frames deviate more than 2px from the "
                                 "median visual centre - nothing to suggest."))
        else:
            lay.addWidget(QLabel(
                f"{len(sug)} frame(s) drift from the median centre.\n"
                "Tick the ones to pull onto the shared anchor, preview, then apply."))
            self.table = QTableWidget(0, 4)
            self.table.setHorizontalHeaderLabels(["", "Frame", "dX", "dY"])
            self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
            for i in sorted(sug):
                row = self.table.rowCount()
                self.table.insertRow(row)
                cb = QCheckBox()
                cb.setChecked(True)
                self.table.setCellWidget(row, 0, cb)
                self.table.setItem(row, 1, QTableWidgetItem(str(i + 1)))
                self.table.setItem(row, 2, QTableWidgetItem(f"{sug[i][0]:+.2f}"))
                self.table.setItem(row, 3, QTableWidgetItem(f"{sug[i][1]:+.2f}"))
            lay.addWidget(self.table)
        btns = QDialogButtonBox()
        self.preview_btn = btns.addButton("Preview", QDialogButtonBox.ActionRole)
        self.preview_btn.clicked.connect(self._preview)
        apply_btn = btns.addButton("Apply", QDialogButtonBox.AcceptRole)
        apply_btn.clicked.connect(self._apply)
        cancel_btn = btns.addButton("Cancel", QDialogButtonBox.RejectRole)
        cancel_btn.clicked.connect(self._cancel)
        lay.addWidget(btns)

    def _checked(self) -> dict:
        out = {}
        for row in range(self.table.rowCount()):
            cb = self.table.cellWidget(row, 0)
            if cb and cb.isChecked():
                i = int(self.table.item(row, 1).text()) - 1
                out[i] = self.sug[i]
        return out

    def _preview(self):
        if self._backup is None:
            self._backup = {i: (f.user_dx, f.user_dy)
                            for i, f in enumerate(self.anim.frames)}
        sel = self._checked()
        for i, (dx, dy) in sel.items():
            f = self.anim.frames[i]
            f.user_dx += dx
            f.user_dy += dy
        gifproc.align(self.anim)
        self.editor.revision += 1
        self.editor.refresh_all()

    def _apply(self):
        # preview already applied the deltas; record undo from backup
        if self._backup is not None:
            old = self._backup
            new = {i: (f.user_dx, f.user_dy) for i, f in enumerate(self.anim.frames)}
            self.editor.push_cmd("stabilize frames",
                                 lambda: self.editor._restore_frame_offsets(self.anim, old),
                                 lambda: self.editor._restore_frame_offsets(self.anim, new))
        self.accept()

    def _cancel(self):
        if self._backup is not None:
            self.editor._restore_frame_offsets(self.anim, self._backup)
            self.editor.revision += 1
            self.editor.refresh_all()
        self.reject()


class ExportTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.char_edit = QLineEdit("character")
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("output folder")
        browse = QPushButton("...")
        browse.setFixedWidth(30)
        browse.clicked.connect(self._browse)
        outrow = QHBoxLayout()
        outrow.addWidget(self.out_edit, 1)
        outrow.addWidget(browse)
        self.preset = QComboBox()
        self.preset.addItems(["psych", "fnf"])
        form.addRow("Character name", self.char_edit)
        form.addRow("Preset", self.preset)
        form.addRow("Output dir", outrow)
        lay.addLayout(form)

        row = QHBoxLayout()
        self.export_btn = QPushButton("Export PNG + XML + JSON")
        self.export_btn.clicked.connect(self._export)
        self.rchr_btn = QPushButton("Pack .RCHR archive")
        self.rchr_btn.clicked.connect(self._pack_rchr)
        row.addWidget(self.export_btn)
        row.addWidget(self.rchr_btn)
        row.addStretch(1)
        lay.addLayout(row)
        self.status = QLabel("")
        lay.addWidget(self.status)
        lay.addStretch(1)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Output folder")
        if d:
            self.out_edit.setText(d)

    def _outdir(self) -> Path | None:
        d = self.out_edit.text().strip()
        if not d:
            d = QFileDialog.getExistingDirectory(self, "Output folder")
            if not d:
                return None
            self.out_edit.setText(d)
        return Path(d)

    def _export(self):
        anims = self.window().animations()
        if not anims:
            self.status.setText("no animations imported")
            return
        out = self._outdir()
        if not out:
            return
        char = self.char_edit.text().strip() or self.window().char_name()
        try:
            res = atlas.export_all(anims, out, char,
                                   preset=self.preset.currentText())
            msg = (f"exported {res['frames']} frames -> {res['png']} "
                   f"({res['size'][0]}x{res['size'][1]})")
            if res.get("warnings"):
                msg += " | " + "; ".join(res["warnings"])
            self.status.setText(msg)
        except Exception as e:  # noqa: BLE001
            self.status.setText(f"export failed: {e}")

    def _pack_rchr(self):
        anims = self.window().animations()
        if not anims:
            self.status.setText("no animations imported")
            return
        out = self._outdir()
        if not out:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save .RCHR", str(out / "character.rchr"),
                                              "RCHR archive (*.rchr)")
        if not path:
            return
        char = self.char_edit.text().strip() or self.window().char_name()
        try:
            res = atlas.pack_character_rchr(anims, path, char)
            self.status.setText(
                f"packed {res['entries']} files, {res['raw_bytes']} -> {res['stored_bytes']} bytes")
        except Exception as e:  # noqa: BLE001
            self.status.setText(f"pack failed: {e}")


class RchrTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText(".rchr archive path")
        openb = QPushButton("Open .RCHR")
        openb.clicked.connect(self._open)
        projb = QPushButton("Open as project")
        projb.clicked.connect(self._open_as_project)
        row.addWidget(QLabel("Archive:"))
        row.addWidget(self.path_edit, 1)
        row.addWidget(openb)
        row.addWidget(projb)
        lay.addLayout(row)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Path", "Raw", "Stored", "Method"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        lay.addWidget(self.table, 1)

        btns = QHBoxLayout()
        self.extract_btn = QPushButton("Extract selected/all to...")
        self.extract_btn.clicked.connect(self._extract)
        btns.addWidget(self.extract_btn)
        self.info = QLabel("")
        btns.addWidget(self.info)
        btns.addStretch(1)
        lay.addLayout(btns)
        self._archive: rchr.Archive | None = None

    def _open(self):
        path = self.path_edit.text().strip()
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Open .RCHR", "", "RCHR archive (*.rchr)")
            if not path:
                return
            self.path_edit.setText(path)
        try:
            self._archive = rchr.Archive(path)
        except Exception as e:  # noqa: BLE001
            self._archive = None
            self.info.setText(f"open failed: {e}")
            return
        self.table.setRowCount(len(self._archive.entries))
        for i, e in enumerate(self._archive.entries):
            self.table.setItem(i, 0, QTableWidgetItem(e.path))
            self.table.setItem(i, 1, QTableWidgetItem(str(e.raw_size)))
            self.table.setItem(i, 2, QTableWidgetItem(str(e.stored_size)))
            self.table.setItem(i, 3, QTableWidgetItem("deflate" if e.method else "store"))
        self.info.setText(f"{len(self._archive.entries)} entries")

    def _extract(self):
        if not self._archive:
            return
        dest = QFileDialog.getExistingDirectory(self, "Extract to")
        if not dest:
            return
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        entries = ([self._archive.entries[r] for r in rows] if rows
                   else list(self._archive.entries))
        ok = 0
        for e in entries:
            try:
                raw = self._archive.read_entry(e)
                out = Path(dest) / e.path
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(raw)
                ok += 1
            except Exception as ex:  # noqa: BLE001
                self.info.setText(f"entry {e.path} failed: {ex}")
        self.info.setText(f"extracted {ok}/{len(entries)} to {dest}")

    def _open_as_project(self):
        path = self.path_edit.text().strip()
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self, "Open sprite project", "", "RCHR project (*.rchr)")
            if not path:
                return
            self.path_edit.setText(path)
        self.window().open_project(path)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FNF Sprite Studio")
        self.resize(1100, 720)
        self._animations: list[Animation] = []

        tabs = QTabWidget()
        self.import_tab = ImportTab()
        self.editor_tab = EditorTab()
        self.export_tab = ExportTab()
        self.rchr_tab = RchrTab()
        tabs.addTab(self.import_tab, "Import")
        tabs.addTab(self.editor_tab, "Editor")
        tabs.addTab(self.export_tab, "Export")
        tabs.addTab(self.rchr_tab, "RCHR")
        self.setCentralWidget(tabs)
    def add_animation(self, anim: Animation):
        self._animations.append(anim)
        self.editor_tab.set_animations(self._animations)
        # nudge imported animations apart on the workspace so they don't
        # stack exactly on top of each other
        n = len(self._animations)
        if n > 1:
            anim.pos_x = (n - 1) * 40.0
        gifproc.align(anim)

    def animations(self) -> list[Animation]:
        return self._animations

    def char_name(self) -> str:
        return self.editor_tab.char_name

    def open_project(self, path: str):
        try:
            anims, char, origin = project.load_project(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Open project", f"failed: {e}")
            return
        self._animations = anims
        self.editor_tab.set_animations(anims)
        self.editor_tab.char_name = char
        self.editor_tab.char_edit.setText(char)
        self.editor_tab.origin = origin
        self.editor_tab.refresh_all()
        # jump to the editor tab
        for i in range(self.centralWidget().count()):
            if self.centralWidget().widget(i) is self.editor_tab:
                self.centralWidget().setCurrentIndex(i)
                break


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("FNF Sprite Studio")
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
