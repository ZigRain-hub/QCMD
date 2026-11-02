# QULW Terminal
# Copyright (c) 2026 [ZigRain-hub]
# Licensed under the MIT License. See LICENSE file for details.

import sys
import colorsys
import platform
import os
import json
import psutil
import ctypes
import getpass
import socket
import subprocess
import threading
import queue
import time
import collections
from pathlib import Path
from ctypes import wintypes

import pyte
from winpty import PtyProcess

from PySide6.QtWidgets import (
    QApplication, QVBoxLayout, QHBoxLayout, QSlider, QLabel,
    QPushButton, QCheckBox, QTextEdit, QWidget, QMenu,
    QStackedWidget, QComboBox, QMessageBox, QDialog,
    QScrollArea, QLineEdit, QFrame, QTabWidget, QGridLayout,
    QGraphicsOpacityEffect, QInputDialog, QFileDialog, QSpinBox
)
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QRect, QThread
from PySide6.QtGui import (
    QPainter, QColor, QPen, QFont, QAction, QTextCursor, QFontMetrics, QPixmap, QKeySequence, QShortcut, QRegion, QPainterPath
)
from qframelesswindow import AcrylicWindow

# пути к файлам рядом с exe
if getattr(sys, "frozen", False):
    HERE = Path(sys.executable).parent.resolve()
else:
    HERE = Path(__file__).parent.resolve()

CONFIG_FILE = str(HERE / "qulw_config.json")
ASCII_FILE = str(HERE / "qulw_ascii.json")
HISTORY_LEN = 5000
DEFAULT_ASCII = r"""
   ######    
   ######    
 ##      ##  
##       ##  
##       ##  
##       ##  
##    _##    
 ## /  \##   
   ####  ##
   ####  ##  
"""

def _self_install_and_relaunch():
    # при первом запуске копируем себя в LocalAppData и перезапускаемся
    import shutil, winreg
    me = Path(sys.executable).resolve()
    target_dir = Path(os.environ["LOCALAPPDATA"]) / "QCmd"
    target = target_dir / "cterm.exe"
    if me == target.resolve():
        return

    try:
        for p in psutil.process_iter(["exe"]):
            try:
                exe = p.info["exe"]
                if exe and Path(exe).resolve() == target and p.pid != os.getpid():
                    sys.exit(0)
            except Exception:
                pass
    except Exception:
        pass

    target_dir.mkdir(parents=True, exist_ok=True)
    copied = False
    try:
        shutil.copy2(me, target)
        copied = True
    except Exception:
        pass

    for f in ("qulw_ascii.json", "qulw_config.json"):
        src, dst = me.parent / f, target_dir / f
        if src.exists() and not dst.exists():
            try: shutil.copy2(src, dst)
            except Exception: pass

    try:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\App Paths\QCmd.exe")
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, str(target))
        winreg.CloseKey(key)
    except Exception: pass
    try:
        lnk = Path(os.environ["USERPROFILE"]) / "Desktop" / "QCmd.lnk"
        subprocess.run(["powershell", "-NoProfile", "-Command",
            f"$ws=New-Object -ComObject WScript.Shell;$s=$ws.CreateShortcut('{lnk}');"
            f"$s.TargetPath='{target}';$s.WorkingDirectory='{target_dir}';$s.Save()"],
            capture_output=True)
    except Exception: pass

    if copied and target.exists():
        subprocess.Popen([str(target)], cwd=str(target_dir))
        sys.exit(0)

def get_sys_info():
    user = getpass.getuser()
    host = socket.gethostname()
    cpu = platform.processor()
    if not cpu or "Intel64 Family" in cpu:
        try:
            cpu = subprocess.check_output("powershell -Command \"(Get-CimInstance Win32_Processor).Name\"", shell=True, stderr=subprocess.DEVNULL).decode('utf-8', errors='ignore').strip()
        except Exception:
            cpu = "Unknown CPU"
    try:
        gpu = subprocess.check_output("powershell -Command \"(Get-CimInstance Win32_VideoController).Name\"", shell=True, stderr=subprocess.DEVNULL).decode('utf-8', errors='ignore').strip()
        gpu = gpu.split('\n')[0].strip()
    except Exception:
        gpu = "Unknown GPU"
    return {
        "user": f"{user}@{host}",
        "os": f"{platform.system()} {platform.release()}",
        "kernel": platform.version(),
        "shell": "cmd.exe",
        "wm": "QULW",
        "cpu": cpu,
        "gpu": gpu
    }


def load_config():
    default_info = get_sys_info()
    default = {
        "blur_level": 50,
        "tint_rgb": [20, 20, 25],
        "border_color": [255, 255, 255, 80],
        "rgb_mode": False,
        "show_fastfetch": True,
        "show_window_controls": True,
        "min_width": 200,
        "min_height": 200,
        "logo_scale": 100,
        "info_scale": 100,
        "fastfetch_border": 1,
        "fastfetch_w_pct": 90,
        "fastfetch_h_pct": 20,
        "fastfetch_min_h": 100,
        "info": default_info,

        "opt_eco_mode": False,
        "opt_idle_render": True,
        "opt_disable_blur": True,
        "opt_blur_bg": True,
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                for k, v in default.items():
                    if k not in data:
                        data[k] = v
                return data
        except Exception:
            pass
    return default


def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def load_ascii_data():
    if os.path.exists(ASCII_FILE):
        try:
            with open(ASCII_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data:
                clean = {str(k): str(v) for k, v in data.items() if v}
                if clean:
                    return clean
        except Exception:
            pass
    return {"Default": DEFAULT_ASCII}


def save_ascii_data(data):
    with open(ASCII_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def make_bar(pct, length=20):
    pct = max(0, min(100, pct))
    filled = int(length * pct / 100)
    return "█" * filled + "░" * (length - filled)


class ScreenWithHistory(pyte.Screen):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.history = collections.deque(maxlen=HISTORY_LEN)
        self._blank = pyte.screens.Char(" ")

    def _line_text(self, y):
        line = self.buffer[y]
        return "".join(line[x].data for x in range(self.columns)).rstrip()

    def index(self):
        if self.cursor.y == self.lines - 1:
            self.history.append(self._line_text(0))
        super().index()


class CommandHistory:
    def __init__(self, maxlen=500):
        self.counter = collections.Counter()
        self.recent = collections.deque(maxlen=maxlen)

    def add(self, cmd):
        cmd = cmd.strip()
        if not cmd:
            return
        self.counter[cmd] += 1
        self.recent.append(cmd)

    def best_match(self, prefix):
        if not prefix:
            return ""
        best = None
        best_score = -1
        for cmd in self.recent:
            if len(cmd) <= len(prefix):
                continue
            if not cmd.startswith(prefix):
                continue
            score = self.counter[cmd] * 1000 - len(cmd)
            if score > best_score:
                best_score = score
                best = cmd
        return best or ""


class ColorPickerDialog(QDialog):
    def __init__(self, initial_color=QColor(255, 255, 255), parent=None):
        super().__init__(parent)
        self.setWindowTitle("выбор цвета")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(300, 380)
        self.color = QColor(initial_color)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        self.setStyleSheet("""
            QDialog { border: 1px solid rgba(255, 255, 255, 0.2); border-radius: 8px; background-color: #1a1a1a; }
            QLabel { color: rgba(255,255,255,0.8); font-family: 'Segoe UI'; font-size: 12px; }
            QSlider::groove:horizontal { height: 4px; background: rgba(255,255,255,0.1); border-radius: 2px; }
            QSlider::sub-page:horizontal { height: 4px; background: rgba(255,255,255,0.8); border-radius: 2px; }
            QSlider::handle:horizontal { width: 14px; height: 14px; margin: -5px 0; background: white; border-radius: 7px; }
        """)
        self.preview = QWidget()
        self.preview.setFixedHeight(50)
        self.preview.setStyleSheet(f"background-color: {self.color.name()}; border-radius: 4px; border: 1px solid rgba(255,255,255,0.2);")
        layout.addWidget(self.preview)
        self.sliders = {}
        for ch in ["R", "G", "B"]:
            row = QHBoxLayout()
            lbl = QLabel(ch)
            lbl.setFixedWidth(15)
            row.addWidget(lbl)
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 255)
            slider.setValue(self.color.red() if ch == "R" else self.color.green() if ch == "G" else self.color.blue())
            slider.valueChanged.connect(self._on_slider)
            row.addWidget(slider)
            self.sliders[ch] = slider
            layout.addLayout(row)
        btn_row = QHBoxLayout()
        btn_ok = QPushButton("ок")
        btn_cancel = QPushButton("отмена")
        for btn, is_ok in [(btn_ok, True), (btn_cancel, False)]:
            btn.setStyleSheet("""
                QPushButton { background: rgba(255,255,255,0.05); color: white; border: 1px solid rgba(255,255,255,0.2); border-radius: 4px; padding: 8px; }
                QPushButton:hover { background: rgba(255,255,255,0.15); }
            """)
            if is_ok:
                btn.clicked.connect(self.accept)
            else:
                btn.clicked.connect(self.reject)
            btn_row.addWidget(btn)
        layout.addLayout(btn_row)

    def _on_slider(self):
        r = self.sliders["R"].value()
        g = self.sliders["G"].value()
        b = self.sliders["B"].value()
        self.color = QColor(r, g, b)
        self.preview.setStyleSheet(f"background-color: {self.color.name()}; border-radius: 4px; border: 1px solid rgba(255,255,255,0.2);")

    def get_color(self):
        return self.color


class PtyReaderThread(QThread):
    def __init__(self, pty_process, q):
        super().__init__()
        self.pty_process = pty_process
        self.q = q
        self.running = True

    def run(self):
        while self.running and self.pty_process and self.pty_process.isalive():
            try:
                data = self.pty_process.read(8192)
                if data:
                    self.q.put(data.encode('utf-8', errors='replace'))
                    self.msleep(1)
                else:
                    self.msleep(5)
            except Exception:
                break

    def stop(self):
        self.running = False


class TermWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)

        self.font = QFont("Cascadia Mono", 10)
        self.font.setStyleHint(QFont.Monospace)
        self.fm = QFontMetrics(self.font)

        self.cell_w = max(6, self.fm.horizontalAdvance("M"))
        self.cell_h = max(12, self.fm.height())

        self.fonts = {}
        for bold in [False, True]:
            for italic in [False, True]:
                f = QFont(self.font)
                f.setBold(bold)
                f.setItalic(italic)
                self.fonts[(bold, italic)] = f

        self.ansi_colors = [
            "#21222c", "#ff5555", "#50fa7b", "#f1fa8c",
            "#bd93f9", "#ff79c6", "#8be9fd", "#f8f8f2",
            "#6272a4", "#ff6e6e", "#69ff94", "#ffffa5",
            "#d6acff", "#ff92df", "#a4ffff", "#ffffff"
        ]
        self.default_fg = QColor(230, 230, 240)
        self.cursor_color = QColor(160, 176, 255, 180)
        self.suggestion_color = QColor(120, 120, 140)

        self.cfg = {}
        self.screen = ScreenWithHistory(80, 24)
        self.stream = pyte.ByteStream(self.screen)
        self.queue = queue.Queue()
        self.pty_process = None
        self.reader_thread = None
        self.lock = threading.Lock()
        self._blink = True
        self._color_cache = {}

        self.scroll_offset = 0

        self.cmd_history = CommandHistory()
        self.suggestion_prompt = ""
        self.suggestion_typed = ""
        self.suggestion_rest = ""

        self.blink_timer = QTimer(self)
        self.blink_timer.timeout.connect(self._toggle_blink)
        self.blink_timer.start(500)

        self.feed_timer = QTimer(self)
        self.feed_timer.timeout.connect(self._process_queue)
        self.feed_timer.start(30)

        self.resize_timer = QTimer(self)
        self.resize_timer.setSingleShot(True)
        self.resize_timer.setInterval(60)
        self.resize_timer.timeout.connect(self._force_resize)

        # eco mode
        self.idle_timer = QTimer(self)
        self.idle_timer.setSingleShot(True)
        self.idle_timer.setInterval(10000)
        self.idle_timer.timeout.connect(self._enter_eco_mode)
        self.is_eco_mode = False
        self.last_render_time = 0

    def _enter_eco_mode(self):
        if not self.cfg.get("opt_eco_mode") or not self.cfg.get("opt_idle_render"):
            return

        self.is_eco_mode = True
        self.feed_timer.setInterval(2000)
        self.blink_timer.stop()
        self.update()

    def _exit_eco_mode(self):
        self.is_eco_mode = False
        self.idle_timer.start()
        if self.feed_timer.interval() != 30:
            self.feed_timer.setInterval(30)
            self.blink_timer.start(500)
            self.update()

    def _toggle_blink(self):
        self._blink = not self._blink
        if self.screen.cursor.hidden:
            return
        cx = self.screen.cursor.x * self.cell_w
        cy = self.screen.cursor.y * self.cell_h
        self.update(QRect(cx, cy, self.cell_w, self.cell_h))

    def start_pty(self, cwd):
        self.stop_pty()
        try:
            self.pty_process = PtyProcess.spawn("cmd.exe", cwd=cwd, dimensions=(self.screen.lines, self.screen.columns))
            self.reader_thread = PtyReaderThread(self.pty_process, self.queue)
            self.reader_thread.start()
        except Exception as e:
            with self.lock:
                self.screen.write(f"Error: {e}\r\n")
            self.update()

    def stop_pty(self):
        if self.pty_process:
            try:
                self.pty_process.close()
            except Exception:
                pass
            self.pty_process = None
        if self.reader_thread:
            self.reader_thread.stop()
            self.reader_thread.wait()
            self.reader_thread = None

    def _process_queue(self):
        if self.is_eco_mode:
            now = time.perf_counter()
            if now - self.last_render_time < 2.0:
                return
            self.last_render_time = now

        start = time.perf_counter()
        budget = 0.012
        processed = False

        while time.perf_counter() - start < budget:
            try:
                data = self.queue.get_nowait()
            except queue.Empty:
                break
            self.stream.feed(data)
            processed = True

        if processed:
            self.update()

    def _line_text_at(self, y):
        line = self.screen.buffer[y]
        return "".join(line[x].data for x in range(self.screen.columns)).rstrip()

    def _get_prompt_and_typed(self):
        y = self.screen.cursor.y
        if y < 0 or y >= self.screen.lines:
            return None, ""
        line = self._line_text_at(y)
        idx = line.rfind(">")
        if idx < 0:
            return None, ""
        prompt = line[:idx + 1]
        typed = line[idx + 1:]
        cursor_in_line = self.screen.cursor.x
        expected = idx + 1 + len(typed)
        if cursor_in_line != expected:
            return None, ""
        return prompt, typed

    def _update_suggestion(self):
        prompt, typed = self._get_prompt_and_typed()
        if prompt is None:
            self.suggestion_prompt = ""
            self.suggestion_typed = ""
            self.suggestion_rest = ""
            return
        self.suggestion_prompt = prompt
        self.suggestion_typed = typed
        best = self.cmd_history.best_match(typed)
        self.suggestion_rest = best[len(typed):] if best else ""

    def _detect_command_end(self):
        y = self.screen.cursor.y
        for prev_y in range(y - 1, max(-1, y - 5), -1):
            line = self._line_text_at(prev_y)
            if not line:
                continue
            idx = line.rfind(">")
            if idx >= 0:
                cmd = line[idx + 1:].strip()
                if cmd:
                    self.cmd_history.add(cmd)
            break

    def _force_resize(self):
        if self.width() <= 0 or self.height() <= 0:
            return

        cols = max(20, self.width() // self.cell_w)
        rows = max(5, self.height() // self.cell_h)

        try:
            size_file = HERE / "cterm_size.txt"
            size_file.write_text(f"{cols} {rows}")
        except Exception:
            pass

        with self.lock:
            old_rows = self.screen.lines
            old_cols = self.screen.columns
            if cols == old_cols and rows == old_rows:
                return

            def empty_line():
                return collections.defaultdict(lambda: self.screen.default_char)

            def empty_buffer():
                return collections.defaultdict(empty_line)

            if rows < old_rows:
                new_buf = empty_buffer()
                for y in range(rows):
                    new_buf[y] = self.screen.buffer[y]
                self.screen.buffer = new_buf
                self.screen.cursor.y = min(self.screen.cursor.y, rows - 1)
                self.screen.lines = rows
            else:
                diff = rows - old_rows
                take = min(diff, len(self.screen.history))
                new_buf = empty_buffer()
                for y in range(old_rows):
                    new_buf[y + take] = self.screen.buffer[y]
                for i in range(take):
                    hist_line = self.screen.history.pop()
                    for x, ch in enumerate(hist_line[:cols]):
                        new_buf[i][x] = pyte.screens.Char(ch)
                self.screen.buffer = new_buf
                self.screen.cursor.y += take
                self.screen.lines = rows

            if cols != old_cols:
                for y in range(self.screen.lines):
                    line = self.screen.buffer[y]
                    if cols < old_cols:
                        for x in range(cols, old_cols):
                            line.pop(x, None)
                    else:
                        for x in range(old_cols, cols):
                            line[x] = self.screen.default_char
                self.screen.columns = cols
                self.screen.cursor.x = min(self.screen.cursor.x, cols - 1)

            self.scroll_offset = 0

            if self.pty_process and self.pty_process.isalive():
                try:
                    self.pty_process.setwinsize(rows, cols)
                except Exception:
                    pass

        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resize_timer.start()
        self._exit_eco_mode()

    def _parse_color(self, color_str):
        key = color_str if color_str else "default"
        cached = self._color_cache.get(key, ...)
        if cached is not ...:
            return cached

        result = None
        if not color_str or color_str == "default":
            result = None
        elif isinstance(color_str, str) and len(color_str) == 6:
            try:
                r = int(color_str[0:2], 16)
                g = int(color_str[2:4], 16)
                b = int(color_str[4:6], 16)
                result = QColor(r, g, b)
            except ValueError:
                pass
        else:
            color_map = {
                "black": 0, "red": 1, "green": 2, "brown": 3, "yellow": 3, "blue": 4,
                "magenta": 5, "cyan": 6, "white": 7,
                "brightblack": 8, "brightred": 9, "brightgreen": 10,
                "brightyellow": 11, "brightblue": 12, "brightmagenta": 13,
                "brightcyan": 14, "brightwhite": 15
            }
            if color_str in color_map:
                result = QColor(self.ansi_colors[color_map[color_str]])
            else:
                try:
                    idx = int(color_str)
                    if 0 <= idx < 16:
                        result = QColor(self.ansi_colors[idx])
                    elif 16 <= idx < 232:
                        idx -= 16
                        result = QColor((idx // 36) * 51, ((idx // 6) % 6) * 51, (idx % 6) * 51)
                    elif 232 <= idx < 256:
                        v = (idx - 232) * 10 + 8
                        result = QColor(v, v, v)
                except Exception:
                    pass

        if len(self._color_cache) > 1024:
            self._color_cache.clear()
        self._color_cache[key] = result
        return result

    def _visible_lines(self):
        buffer_lines = [self.screen.buffer[y] for y in range(self.screen.lines)]
        if self.scroll_offset > 0 and self.screen.history:
            lines = []
            for i in range(self.screen.lines):
                hist_idx = len(self.screen.history) - self.scroll_offset + i
                if hist_idx < 0:
                    lines.append(buffer_lines[i])
                elif hist_idx < len(self.screen.history):
                    lines.append(self.screen.history[hist_idx])
                else:
                    lines.append(buffer_lines[hist_idx - len(self.screen.history)])
            return lines, True
        return buffer_lines, False

    def paintEvent(self, event):
        if self.width() <= 0 or self.height() <= 0:
            return

        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.TextAntialiasing)
            with self.lock:
                lines, scrolled = self._visible_lines()

                rows = min(self.screen.lines, self.height() // self.cell_h + 1)
                cols = min(self.screen.columns, self.width() // self.cell_w + 1)
                ascent = self.fm.ascent()

                normal_font = self.fonts[(False, False)]
                default_fg = self.default_fg

                p.setFont(normal_font)
                p.setPen(default_fg)

                for y in range(rows):
                    line = lines[y]
                    y_px = y * self.cell_h

                    if isinstance(line, str):
                        text = line[:cols]
                        if text.strip():
                            p.drawText(0, y_px + ascent, text)
                        continue

                    x = 0
                    while x < cols:
                        char = line[x]
                        fg = self._parse_color(char.fg) or default_fg
                        bg = self._parse_color(char.bg)
                        font = self.fonts[(char.bold, char.italics)]

                        start = x

                        while (
                            x < cols
                            and line[x].fg == char.fg
                            and line[x].bg == char.bg
                            and line[x].bold == char.bold
                            and line[x].italics == char.italics
                        ):
                            x += 1

                        text = "".join(line[i].data or " " for i in range(start, x))

                        if bg:
                            p.fillRect(
                                start * self.cell_w,
                                y_px,
                                (x - start) * self.cell_w,
                                self.cell_h,
                                bg,
                            )

                        if text.strip():
                            if font != p.font():
                                p.setFont(font)
                            if fg != p.pen().color():
                                p.setPen(fg)
                            p.drawText(start * self.cell_w, y_px + ascent, text)

                if (
                    not scrolled
                    and self.hasFocus()
                    and not self.screen.cursor.hidden
                    and self._blink
                ):
                    p.fillRect(
                        self.screen.cursor.x * self.cell_w,
                        self.screen.cursor.y * self.cell_h,
                        self.cell_w,
                        self.cell_h,
                        self.cursor_color,
                    )

                if not scrolled and self.suggestion_rest:
                    p.setFont(normal_font)
                    p.setPen(self.suggestion_color)
                    p.drawText(
                        self.screen.cursor.x * self.cell_w,
                        self.screen.cursor.y * self.cell_h + ascent,
                        self.suggestion_rest,
                    )

        finally:
            p.end()

    def mousePressEvent(self, event):
        self.setFocus(Qt.MouseFocusReason)
        self._exit_eco_mode()
        super().mousePressEvent(event)

    def wheelEvent(self, event):
        self._exit_eco_mode()
        if not self.screen.history:
            return
        delta = event.angleDelta().y()
        step = 3 if event.modifiers() & Qt.ShiftModifier else 1
        if delta > 0:
            self.scroll_offset = min(
                self.scroll_offset + step,
                len(self.screen.history),
            )
        else:
            self.scroll_offset = max(0, self.scroll_offset - step)
        self.update()

    def contextMenuEvent(self, event):
        self._exit_eco_mode()
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background-color: #1a1a1a; color: #ccc; border: 1px solid rgba(255,255,255,0.2); }"
            "QMenu::item:selected { background-color: rgba(255,255,255,0.1); color: white; }"
        )

        if self.suggestion_rest:
            label = self.suggestion_rest.strip()
            act = menu.addAction(f"вставить подсказку: {label}")
            act.triggered.connect(self._accept_suggestion)

        act_copy = menu.addAction("копировать")
        act_copy.triggered.connect(self._copy_selection)
        act_paste = menu.addAction("вставить")
        act_paste.triggered.connect(self._paste)

        menu.addSeparator()
        if hasattr(self.parent(), "main_window") and self.parent().main_window:
            act_custom = menu.addAction("кастомизация")
            act_custom.triggered.connect(self.parent().main_window.show_settings)

        if hasattr(self.parent(), "main_window") and self.parent().main_window and not self.parent().main_window.cfg.get("show_window_controls", True):
            act_exit = menu.addAction("выход (Alt+F4)")
            act_exit.triggered.connect(self.parent().main_window.close)

        menu.exec(event.globalPos())
        event.accept()

    def _accept_suggestion(self):
        if not self.suggestion_rest:
            return
        if self.pty_process and self.pty_process.isalive():
            try:
                self.pty_process.write(self.suggestion_rest)
            except Exception:
                pass
        self.suggestion_rest = ""

    def _copy_selection(self):
        QApplication.clipboard().setText("")

    def _paste(self):
        if self.pty_process and self.pty_process.isalive():
            try:
                self.pty_process.write(QApplication.clipboard().text())
            except Exception:
                pass

    def keyPressEvent(self, event):
        if self.scroll_offset:
            self.scroll_offset = 0
        if not self.pty_process or not self.pty_process.isalive():
            return

        self._exit_eco_mode()

        key = event.key()
        mods = event.modifiers()
        if event.matches(QKeySequence.Paste):
            text = QApplication.clipboard().text()
            self.pty_process.write(text)
        elif key == Qt.Key_Return or key == Qt.Key_Enter:
            self.pty_process.write("\r")
        elif key == Qt.Key_Backspace:
            self.pty_process.write("\x7f")
        elif key == Qt.Key_Tab:
            self.pty_process.write("\t")
        elif key == Qt.Key_Escape:
            self.pty_process.write("\x1b")
        elif key == Qt.Key_Up:
            self.pty_process.write("\x1b[A")
        elif key == Qt.Key_Down:
            self.pty_process.write("\x1b[B")
        elif key == Qt.Key_Right:
            self.pty_process.write("\x1b[C")
        elif key == Qt.Key_Left:
            self.pty_process.write("\x1b[D")
        elif key == Qt.Key_C and mods & Qt.ControlModifier:
            self.pty_process.write("\x03")
        else:
            text = event.text()
            if text:
                self.pty_process.write(text)


class TerminalView(QWidget):
    def __init__(self, parent=None, config=None):
        super().__init__(parent)
        self.main_window = parent
        self.cfg = config
        # если запущено из system32 запускаем  из домашней папки
        try:
            cwd = os.getcwd()
            if not cwd or cwd.lower().startswith(os.environ["WINDIR"].lower()):
                cwd = os.path.expanduser("~")
        except Exception:
            cwd = os.path.expanduser("~")
        self.cwd = cwd
        self.ascii_data = load_ascii_data()
        self.active_ascii_name = next(iter(self.ascii_data), "Default")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(20, 20, 20, 20)
        self.layout.setSpacing(10)
        self.layout_resize_timer = QTimer(self)
        self.layout_resize_timer.setSingleShot(True)
        self.layout_resize_timer.setInterval(140)
        self.layout_resize_timer.timeout.connect(self._do_force_resize)

        self._ff_debounce = QTimer(self)
        self._ff_debounce.setSingleShot(True)
        self._ff_debounce.setInterval(80)
        self._ff_debounce.timeout.connect(self._update_fastfetch_geometry)

        self.fastfetch_frame = QFrame()
        self.layout.addWidget(self.fastfetch_frame, alignment=Qt.AlignHCenter)
        self.term = TermWidget(self)
        self.term.cfg = config
        self.layout.addWidget(self.term, 1)
        self.lbl_logo = None
        self.is_image_logo = False
        self.orig_pixmap = None
        self.info_labels = []
        self.init_ui()
        self.term.start_pty(self.cwd)
        self.term.setFocus()

    def init_ui(self):
        if self.cfg.get("show_fastfetch", True):
            self.fastfetch_frame.show()
            self._build_fastfetch()
        else:
            self.fastfetch_frame.hide()

    def update_terminal_layout(self):
        self.layout.activate()
        self.layout_resize_timer.start()

    def _do_force_resize(self):
        if not hasattr(self, "term") or not self.term:
            return

        self.layout.activate()
        self.term._force_resize()
        self.term.update()
        self.term.setFocus()

    def _update_fastfetch_geometry(self):
        w_pct = self.cfg.get("fastfetch_w_pct", 90) / 100.0
        h_pct = self.cfg.get("fastfetch_h_pct", 20) / 100.0
        avail_w = self.width() - 40
        avail_h = self.height() - 40
        w = int(avail_w * w_pct)
        calc_h = int(avail_h * h_pct)
        min_h = self.cfg.get("fastfetch_min_h", 100)
        h = max(min_h, calc_h)
        w = max(1, w)
        h = max(1, h)
        if self.fastfetch_frame.width() != w or self.fastfetch_frame.height() != h:
            self.fastfetch_frame.setFixedSize(w, h)
        QTimer.singleShot(30, self._scale_fastfetch)
        if hasattr(self, "layout_resize_timer"):
            self.layout_resize_timer.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._ff_debounce.start()

    def _build_fastfetch(self):
        border_w = self.cfg.get("fastfetch_border", 1)
        self.fastfetch_frame.setStyleSheet(
            f"QFrame {{ border: {border_w}px solid rgba(255, 255, 255, 0.15); border-radius: 10px; background: transparent; }}"
        )
        if self.fastfetch_frame.layout():
            old_layout = self.fastfetch_frame.layout()
            while old_layout.count():
                item = old_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
                elif item.layout():
                    while item.layout().count():
                        sub = item.layout().takeAt(0)
                        if sub.widget():
                            sub.widget().deleteLater()
        else:
            ff_layout = QHBoxLayout(self.fastfetch_frame)
            ff_layout.setContentsMargins(20, 20, 20, 20)
            ff_layout.setSpacing(30)
        ff_layout = self.fastfetch_frame.layout()
        logo_data = self.ascii_data.get(self.active_ascii_name, "")
        if logo_data.startswith("file:///"):
            self.is_image_logo = True
            path = logo_data.replace("file:///", "")
            self.orig_pixmap = QPixmap(path)
            self.lbl_logo = QLabel()
            if not self.orig_pixmap.isNull():
                self.lbl_logo.setPixmap(self.orig_pixmap)
            else:
                self.lbl_logo.setText("Image not found")
        else:
            self.is_image_logo = False
            self.lbl_logo = QLabel(logo_data)
        self.lbl_logo.setStyleSheet("color: rgba(255, 255, 255, 0.8); border: none;")
        self.lbl_logo.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        ff_layout.addWidget(self.lbl_logo, alignment=Qt.AlignVCenter)
        info_widget = QWidget()
        info_widget.setStyleSheet("border: none;")
        grid = QGridLayout(info_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(6)
        info = self.cfg.get("info", get_sys_info())
        try:
            mem = psutil.virtual_memory()
            mem_bar = make_bar(mem.percent)
            disk = psutil.disk_usage('/')
            disk_bar = make_bar(disk.percent)
            mem_pct, disk_pct = mem.percent, disk.percent
        except Exception:
            mem_bar, disk_bar = make_bar(0), make_bar(0)
            mem_pct, disk_pct = 0, 0
        info_data = [
            ("user", info.get("user", "unknown")),
            ("os", info.get("os", "unknown")),
            ("kernel", info.get("kernel", "unknown")),
            ("shell", info.get("shell", "unknown")),
            ("wm", info.get("wm", "unknown")),
            ("cpu", info.get("cpu", "unknown")),
            ("gpu", info.get("gpu", "unknown")),
            ("memory", f"[{mem_bar}] {mem_pct}%"),
            ("disk", f"[{disk_bar}] {disk_pct}%"),
        ]
        self.info_labels = []
        for row, (key, val) in enumerate(info_data):
            lbl_key = QLabel(key)
            lbl_key.setStyleSheet("color: rgba(255, 255, 255, 0.4); border: none;")
            lbl_val = QLabel(str(val))
            lbl_val.setStyleSheet("color: rgba(255, 255, 255, 0.9); border: none;")
            grid.addWidget(lbl_key, row, 0)
            grid.addWidget(lbl_val, row, 1)
            self.info_labels.extend([lbl_key, lbl_val])
        ff_layout.addWidget(info_widget, alignment=Qt.AlignVCenter)
        ff_layout.addStretch(1)

    def _scale_fastfetch(self):
        if not self.lbl_logo:
            return
        avail_w = self.fastfetch_frame.width() - 300
        avail_h = self.fastfetch_frame.height() - 40
        if avail_w < 50 or avail_h < 50:
            return
        logo_scale = self.cfg.get("logo_scale", 100) / 100.0
        info_scale = self.cfg.get("info_scale", 100) / 100.0
        if self.is_image_logo:
            if self.orig_pixmap and not self.orig_pixmap.isNull():
                target_w = max(10, int(avail_w * logo_scale))
                target_h = max(10, int(avail_h * logo_scale))
                scaled = self.orig_pixmap.scaled(target_w, target_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.lbl_logo.setPixmap(scaled)
        else:
            text = self.lbl_logo.text()
            lines = text.split('\n')
            num_lines = len(lines)
            max_len = max([len(l) for l in lines]) if lines else 0
            if max_len > 0 and num_lines > 0:
                size_w = int(avail_w / (max_len * 0.6))
                size_h = int(avail_h / (num_lines * 1.2))
                auto_size = max(3, min(size_w, size_h))
                final_size = max(1, int(auto_size * logo_scale))
                self.lbl_logo.setFont(QFont("Consolas", final_size))
        if self.info_labels:
            max_chars = 0
            for lbl in self.info_labels:
                max_chars = max(max_chars, len(lbl.text()))
            info_avail_w = self.fastfetch_frame.width() - (avail_w + 100)
            if info_avail_w > 100:
                auto_info_size = int(info_avail_w / (max_chars * 0.55))
            else:
                auto_info_size = 8
            final_info_size = max(1, int(auto_info_size * info_scale))
            for lbl in self.info_labels:
                lbl.setFont(QFont("Cascadia Mono", final_info_size))

    def set_fastfetch_visible(self, visible):
        self.cfg["show_fastfetch"] = visible
        self.init_ui()
        self.update_terminal_layout()

    def set_active_ascii(self, name, data):
        self.ascii_data = data
        self.active_ascii_name = name
        self.init_ui()
        self.update_terminal_layout()

    def contextMenuEvent(self, event):
        if self.main_window:
            self.main_window.show_custom_context_menu(event.globalPos())
        event.accept()

    def closeEvent(self, event):
        self.term.stop_pty()
        super().closeEvent(event)


class SettingsView(QWidget):
    def __init__(self, parent_window, config):
        super().__init__(parent_window)
        self.main_win = parent_window
        self.cfg = config
        self.ascii_data = load_ascii_data()
        self.current_editing_name = next(iter(self.ascii_data), "Default")
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(10)
        header = QHBoxLayout()
        title = QLabel("Кастомизация")
        title.setStyleSheet("color: white; font-size: 16px; font-weight: bold;")
        header.addWidget(title)
        header.addStretch(1)
        btn_back = QPushButton("← вернуться")
        btn_back.setStyleSheet("""
            QPushButton { background: rgba(255,255,255,0.05); color: white; border: 1px solid rgba(255,255,255,0.2); border-radius: 4px; padding: 6px 12px; }
            QPushButton:hover { background: rgba(255,255,255,0.15); }
        """)
        btn_back.clicked.connect(self.main_win.show_terminal)
        header.addWidget(btn_back)
        main_layout.addLayout(header)
        tabs = QTabWidget()
        tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid rgba(255,255,255,0.1); background: rgba(0,0,0,0.2); border-radius: 4px; }
            QTabBar::tab { background: transparent; color: rgba(255,255,255,0.5); padding: 8px 16px; border-bottom: 2px solid transparent; }
            QTabBar::tab:selected { color: white; border-bottom: 2px solid white; }
            QTabBar::tab:hover { color: rgba(255,255,255,0.8); }
        """)
        main_layout.addWidget(tabs)
        tab_appearance = QWidget()
        app_layout = QVBoxLayout(tab_appearance)
        app_layout.setSpacing(10)
        app_layout.setContentsMargins(15, 15, 15, 15)
        self.chk_fastfetch = QCheckBox("показывать fastfetch")
        self.chk_fastfetch.setStyleSheet("color: rgba(255,255,255,0.8); font-size: 13px;")
        self.chk_fastfetch.setChecked(self.cfg.get("show_fastfetch", True))
        self.chk_fastfetch.stateChanged.connect(self._toggle_fastfetch)
        app_layout.addWidget(self.chk_fastfetch)
        window_settings_layout = QGridLayout()
        window_settings_layout.setSpacing(10)
        self.chk_controls = QCheckBox("показывать кнопки окна (свернуть/развернуть/закрыть)")
        self.chk_controls.setStyleSheet("color: rgba(255,255,255,0.8); font-size: 13px;")
        self.chk_controls.setChecked(self.cfg.get("show_window_controls", True))
        self.chk_controls.stateChanged.connect(self._toggle_controls)
        window_settings_layout.addWidget(self.chk_controls, 0, 0, 1, 2)
        hint_label = QLabel("если кнопки скрыты, закрыть можно через Alt+F4 или пкм -> выход")
        hint_label.setStyleSheet("color: rgba(255,255,255,0.4); font-size: 11px;")
        window_settings_layout.addWidget(hint_label, 1, 0, 1, 2)
        window_settings_layout.addWidget(QLabel("мин. ширина (px):"), 2, 0)
        self.spin_min_w = QSpinBox()
        self.spin_min_w.setRange(20, 1000)
        self.spin_min_w.setValue(self.cfg.get("min_width", 200))
        self.spin_min_w.valueChanged.connect(self._change_min_size)
        window_settings_layout.addWidget(self.spin_min_w, 2, 1)
        window_settings_layout.addWidget(QLabel("мин. высота (px):"), 3, 0)
        self.spin_min_h = QSpinBox()
        self.spin_min_h.setRange(20, 1000)
        self.spin_min_h.setValue(self.cfg.get("min_height", 200))
        self.spin_min_h.valueChanged.connect(self._change_min_size)
        window_settings_layout.addWidget(self.spin_min_h, 3, 1)
        app_layout.addLayout(window_settings_layout)
        row_blur = QHBoxLayout()
        lbl_blur = QLabel("прозрачность окна:")
        lbl_blur.setStyleSheet("color: rgba(255,255,255,0.8);")
        row_blur.addWidget(lbl_blur)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(self.cfg.get("blur_level", 50))
        self.slider.valueChanged.connect(self.main_win._on_slider)
        self.slider.setStyleSheet("""
            QSlider::groove:horizontal { height: 2px; background: rgba(255,255,255,0.2); border-radius: 1px; }
            QSlider::sub-page:horizontal { height: 2px; background: white; border-radius: 1px; }
            QSlider::add-page:horizontal { height: 2px; background: rgba(255,255,255,0.2); border-radius: 1px; }
            QSlider::handle:horizontal { width: 12px; height: 12px; margin: -5px 0; background: white; border-radius: 6px; }
        """)
        row_blur.addWidget(self.slider, 1)
        app_layout.addLayout(row_blur)
        row_colors = QHBoxLayout()
        self.btn_tint = QPushButton("цвет фона")
        self.btn_tint.clicked.connect(self.main_win._choose_tint)
        self._update_btn_style(self.btn_tint, self.cfg.get("tint_rgb", [20, 20, 25]))
        row_colors.addWidget(self.btn_tint)
        self.btn_border = QPushButton("цвет обводки")
        self.btn_border.clicked.connect(self.main_win._choose_border)
        bc = self.cfg.get("border_color", [255, 255, 255, 80])
        self._update_btn_style(self.btn_border, bc[:3])
        row_colors.addWidget(self.btn_border)
        self.chk_rgb = QCheckBox("rgb переливание")
        self.chk_rgb.setStyleSheet("color: rgba(255,255,255,0.8); font-size: 13px;")
        self.chk_rgb.setChecked(self.cfg.get("rgb_mode", False))
        self.chk_rgb.stateChanged.connect(self.main_win._toggle_rgb)
        row_colors.addWidget(self.chk_rgb)
        app_layout.addLayout(row_colors)
        app_layout.addStretch(1)

        # оптимизация
        tab_opt = QWidget()
        opt_layout = QVBoxLayout(tab_opt)
        opt_layout.setSpacing(10)
        opt_layout.setContentsMargins(15, 15, 15, 15)

        opt_title = QLabel("режим энергосбережения")
        opt_title.setStyleSheet("color: white; font-size: 14px; font-weight: bold;")
        opt_layout.addWidget(opt_title)

        self.chk_eco = QCheckBox("включить оптимизацию (eco mode)")
        self.chk_eco.setStyleSheet("color: white; font-size: 14px; font-weight: bold;")
        self.chk_eco.setChecked(self.cfg.get("opt_eco_mode", False))
        self.chk_eco.stateChanged.connect(self._toggle_eco)
        opt_layout.addWidget(self.chk_eco)

        self.chk_opt_blur = QCheckBox("убирать блюр при включении оптимизации")
        self.chk_opt_blur.setStyleSheet("color: rgba(255,255,255,0.8); font-size: 13px;")
        self.chk_opt_blur.setChecked(self.cfg.get("opt_disable_blur", True))
        self.chk_opt_blur.stateChanged.connect(self._toggle_opt_blur)
        opt_layout.addWidget(self.chk_opt_blur)

        self.chk_opt_idle = QCheckBox("снижать fps интерфейса при простое (10 сек -> 0.5 fps)")
        self.chk_opt_idle.setStyleSheet("color: rgba(255,255,255,0.8); font-size: 13px;")
        self.chk_opt_idle.setChecked(self.cfg.get("opt_idle_render", True))
        self.chk_opt_idle.stateChanged.connect(self._toggle_opt_idle)
        opt_layout.addWidget(self.chk_opt_idle)

        self.chk_blur_bg = QCheckBox("блюр на фон (включить размытие)")
        self.chk_blur_bg.setStyleSheet("color: rgba(255,255,255,0.8); font-size: 13px;")
        self.chk_blur_bg.setChecked(self.cfg.get("opt_blur_bg", True))
        self.chk_blur_bg.stateChanged.connect(self._toggle_blur_bg)
        opt_layout.addWidget(self.chk_blur_bg)

        opt_layout.addStretch(1)

        tabs.addTab(tab_appearance, "внешний вид")
        tabs.insertTab(1, tab_opt, "оптимизация")

        tab_term = QWidget()
        term_layout = QHBoxLayout(tab_term)
        term_layout.setSpacing(15)
        term_layout.setContentsMargins(15, 15, 15, 15)
        left_panel = QVBoxLayout()
        ascii_row = QHBoxLayout()
        self.combo_ascii = QComboBox()
        self.combo_ascii.setStyleSheet("background: rgba(255,255,255,0.05); color: white; border: 1px solid rgba(255,255,255,0.2); padding: 4px;")
        self.combo_ascii.addItems(self.ascii_data.keys())
        self.combo_ascii.currentTextChanged.connect(self._on_ascii_select)
        ascii_row.addWidget(self.combo_ascii, 1)
        btn_new = QPushButton("создать")
        btn_new.clicked.connect(self._ascii_new)
        btn_del = QPushButton("удалить")
        btn_del.clicked.connect(self._ascii_delete)
        for b in (btn_new, btn_del):
            b.setStyleSheet("background: rgba(255,255,255,0.05); color: white; border: 1px solid rgba(255,255,255,0.2); border-radius: 4px; padding: 4px 8px;")
            ascii_row.addWidget(b)
        left_panel.addLayout(ascii_row)
        btn_img = QPushButton("загрузить картинку (.png / .jpg)")
        btn_img.setStyleSheet("background: rgba(255,255,255,0.1); color: white; border: 1px solid rgba(255,255,255,0.3); border-radius: 4px; padding: 6px;")
        btn_img.clicked.connect(self._load_image)
        left_panel.addWidget(btn_img)
        row_font = QHBoxLayout()
        row_font.addWidget(QLabel("масштаб лого (%):"))
        self.spin_logo_scale = QSpinBox()
        self.spin_logo_scale.setRange(10, 200)
        self.spin_logo_scale.setSuffix("%")
        self.spin_logo_scale.setSingleStep(5)
        self.spin_logo_scale.setValue(self.cfg.get("logo_scale", 100))
        self.spin_logo_scale.valueChanged.connect(self._change_logo_scale)
        row_font.addWidget(self.spin_logo_scale)
        row_font.addWidget(QLabel("текст (%):"))
        self.spin_info_scale = QSpinBox()
        self.spin_info_scale.setRange(10, 200)
        self.spin_info_scale.setSuffix("%")
        self.spin_info_scale.setSingleStep(5)
        self.spin_info_scale.setValue(self.cfg.get("info_scale", 100))
        self.spin_info_scale.valueChanged.connect(self._change_info_scale)
        row_font.addWidget(self.spin_info_scale)
        row_font.addStretch(1)
        left_panel.addLayout(row_font)
        self.ascii_editor = QTextEdit()
        self.ascii_editor.setFont(QFont("Consolas", 10))
        self.ascii_editor.setStyleSheet("background: rgba(0,0,0,0.3); color: white; border: 1px solid rgba(255,255,255,0.1); border-radius: 4px;")
        self.ascii_editor.setText(self.ascii_data[self.current_editing_name])
        left_panel.addWidget(self.ascii_editor, 1)
        btn_save = QPushButton("сохранить лого")
        btn_save.setStyleSheet("background: rgba(255, 255, 255, 0.1); color: white; border: 1px solid rgba(255, 255, 255, 0.3); border-radius: 4px; padding: 6px;")
        btn_save.clicked.connect(self._ascii_save)
        left_panel.addWidget(btn_save)
        term_layout.addLayout(left_panel, 1)
        right_panel = QVBoxLayout()
        ff_settings = QGridLayout()
        ff_settings.addWidget(QLabel("обводка (px):"), 0, 0)
        self.spin_border = QSpinBox()
        self.spin_border.setRange(0, 10)
        self.spin_border.setValue(self.cfg.get("fastfetch_border", 1))
        self.spin_border.valueChanged.connect(self._change_ff_border)
        ff_settings.addWidget(self.spin_border, 0, 1)
        ff_settings.addWidget(QLabel("ширина (%):"), 1, 0)
        self.spin_w = QSpinBox()
        self.spin_w.setRange(10, 100)
        self.spin_w.setValue(self.cfg.get("fastfetch_w_pct", 90))
        self.spin_w.valueChanged.connect(self._change_ff_size)
        ff_settings.addWidget(self.spin_w, 1, 1)
        ff_settings.addWidget(QLabel("высота (%):"), 2, 0)
        self.spin_h = QSpinBox()
        self.spin_h.setRange(5, 100)
        self.spin_h.setValue(self.cfg.get("fastfetch_h_pct", 20))
        self.spin_h.valueChanged.connect(self._change_ff_size)
        ff_settings.addWidget(self.spin_h, 2, 1)
        ff_settings.addWidget(QLabel("мин. высота (px):"), 3, 0)
        self.spin_min_h_ff = QSpinBox()
        self.spin_min_h_ff.setRange(50, 1000)
        self.spin_min_h_ff.setValue(self.cfg.get("fastfetch_min_h", 100))
        self.spin_min_h_ff.valueChanged.connect(self._change_ff_min_h)
        ff_settings.addWidget(self.spin_min_h_ff, 3, 1)
        right_panel.addLayout(ff_settings)
        right_panel.addWidget(QLabel("информация в fastfetch:"))
        grid = QGridLayout()
        self.info_inputs = {}
        info = self.cfg.get("info", get_sys_info())
        fields = ["user", "os", "kernel", "shell", "wm", "cpu", "gpu"]
        for i, key in enumerate(fields):
            lbl = QLabel(key.capitalize())
            lbl.setStyleSheet("color: rgba(255,255,255,0.7);")
            inp = QLineEdit()
            inp.setText(info.get(key, ""))
            inp.setStyleSheet("background: rgba(255,255,255,0.05); color: white; border: 1px solid rgba(255,255,255,0.2); padding: 4px; border-radius: 2px;")
            inp.textChanged.connect(self._info_changed)
            self.info_inputs[key] = inp
            grid.addWidget(lbl, i, 0)
            grid.addWidget(inp, i, 1)
        right_panel.addLayout(grid)
        right_panel.addStretch(1)
        term_layout.addLayout(right_panel, 1)
        tabs.addTab(tab_term, "терминал")
        self.main_win.register_settings_view(self)

    def _toggle_eco(self, state):
        self.cfg["opt_eco_mode"] = (state == Qt.Checked.value)
        save_config(self.cfg)
        if self.cfg["opt_eco_mode"]:
            self.main_win.term_view.term._enter_eco_mode()
        else:
            self.main_win.term_view.term._exit_eco_mode()
        self.main_win._update_blur()

    def _toggle_opt_blur(self, state):
        self.cfg["opt_disable_blur"] = (state == Qt.Checked.value)
        save_config(self.cfg)
        self.main_win._update_blur()

    def _toggle_opt_idle(self, state):
        self.cfg["opt_idle_render"] = (state == Qt.Checked.value)
        save_config(self.cfg)
        if not self.cfg["opt_idle_render"]:
            self.main_win.term_view.term._exit_eco_mode()

    def _toggle_blur_bg(self, state):
        self.cfg["opt_blur_bg"] = (state == Qt.Checked.value)
        save_config(self.cfg)
        self.main_win._update_blur()

    def _toggle_fastfetch(self, state):
        self.cfg["show_fastfetch"] = (state == Qt.Checked.value)
        save_config(self.cfg)
        self.main_win.term_view.set_fastfetch_visible(self.cfg["show_fastfetch"])

    def _toggle_controls(self, state):
        self.cfg["show_window_controls"] = (state == Qt.Checked.value)
        save_config(self.cfg)
        self.main_win.top_bar.setVisible(self.cfg["show_window_controls"])

    def _change_min_size(self):
        w = self.spin_min_w.value()
        h = self.spin_min_h.value()
        self.cfg["min_width"] = w
        self.cfg["min_height"] = h
        save_config(self.cfg)
        self.main_win.setMinimumSize(w, h)

    def _on_ascii_select(self, name):
        if name in self.ascii_data:
            self.current_editing_name = name
            data = self.ascii_data[name]
            if data.startswith("file:///"):
                self.ascii_editor.setText("[это картинка. путь: " + data.replace("file:///", "") + "]")
            else:
                self.ascii_editor.setText(data)

    def _ascii_new(self):
        name, ok = QInputDialog.getText(self, "новый логотип", "введите имя:")
        if ok and name.strip():
            name = name.strip()
            self.ascii_data[name] = ""
            self.combo_ascii.addItem(name)
            self.combo_ascii.setCurrentText(name)

    def _ascii_delete(self):
        if len(self.ascii_data) <= 1:
            QMessageBox.warning(self, "ошибка", "должен остаться хотя бы один логотип!")
            return
        name = self.current_editing_name
        del self.ascii_data[name]
        self.combo_ascii.removeItem(self.combo_ascii.currentIndex())
        self.current_editing_name = self.combo_ascii.currentText()
        self._on_ascii_select(self.current_editing_name)

    def _load_image(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "выбрать картинку", "", "Images (*.png *.jpg *.jpeg)")
        if file_path:
            data_str = f"file:///{file_path.replace('\\\\', '/')}"
            self.ascii_data[self.current_editing_name] = data_str
            self.ascii_editor.setText(f"[картинка загружена: {os.path.basename(file_path)}]")
            save_ascii_data(self.ascii_data)
            self.main_win.term_view.set_active_ascii(self.current_editing_name, self.ascii_data)

    def _ascii_save(self):
        text = self.ascii_editor.toPlainText()
        if not text.startswith("[картинка загружена:") and not text.startswith("[это картинка."):
            self.ascii_data[self.current_editing_name] = text
        save_ascii_data(self.ascii_data)
        self.main_win.term_view.set_active_ascii(self.current_editing_name, self.ascii_data)

    def _change_logo_scale(self, val):
        self.cfg["logo_scale"] = val
        save_config(self.cfg)
        self.main_win.term_view._scale_fastfetch()

    def _change_info_scale(self, val):
        self.cfg["info_scale"] = val
        save_config(self.cfg)
        self.main_win.term_view._scale_fastfetch()

    def _change_ff_border(self, val):
        self.cfg["fastfetch_border"] = val
        save_config(self.cfg)
        self.main_win.term_view._build_fastfetch()

    def _change_ff_size(self):
        self.cfg["fastfetch_w_pct"] = self.spin_w.value()
        self.cfg["fastfetch_h_pct"] = self.spin_h.value()
        save_config(self.cfg)
        self.main_win.term_view._update_fastfetch_geometry()

    def _change_ff_min_h(self, val):
        self.cfg["fastfetch_min_h"] = val
        save_config(self.cfg)
        self.main_win.term_view._update_fastfetch_geometry()

    def _info_changed(self):
        for k, inp in self.info_inputs.items():
            self.cfg["info"][k] = inp.text()
        save_config(self.cfg)
        self.main_win.term_view._build_fastfetch()

    def _update_btn_style(self, btn, rgb):
        r, g, b = rgb
        btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 255, 255, 0.05); color: white;
                border: 1px solid rgba(255,255,255,0.2); border-radius: 4px; padding: 6px 12px;
            }}
            QPushButton:hover {{ background: rgba(255,255,255,0.15); }}
        """)

    def sync_colors(self):
        self._update_btn_style(self.btn_tint, self.cfg.get("tint_rgb", [20, 20, 25]))
        bc = self.cfg.get("border_color", [255, 255, 255, 80])
        self._update_btn_style(self.btn_border, bc[:3])


class Window(AcrylicWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QULW Terminal")
        self.resize(1000, 700)
        self.cfg = load_config()
        self.setMinimumSize(self.cfg.get("min_width", 200), self.cfg.get("min_height", 200))

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        if hasattr(self, "titleBar"):
            self.titleBar.hide()

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(1, 1, 1, 1)
        main_layout.setSpacing(0)
        self.top_bar = QWidget()
        self.top_bar.setFixedHeight(32)
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(0, 0, 8, 0)
        top_layout.setSpacing(4)
        top_layout.addStretch(1)

        def make_btn(text, hover_bg, click_func):
            btn = QPushButton(text)
            btn.setFixedSize(36, 24)
            btn.setStyleSheet(f"""
                QPushButton {{ background: transparent; color: rgba(255,255,255,0.7); border: none; font-family: 'Segoe UI'; font-size: 12px; border-radius: 4px; }}
                QPushButton:hover {{ background: {hover_bg}; color: white; }}
            """)
            btn.clicked.connect(click_func)
            return btn

        self.btn_min = make_btn("—", "rgba(255,255,255,0.1)", self.showMinimized)
        self.btn_max = make_btn("□", "rgba(255,255,255,0.1)", self.toggle_maximize)
        self.btn_close = make_btn("✕", "rgba(255,50,50,0.8)", self.close)
        top_layout.addWidget(self.btn_min)
        top_layout.addWidget(self.btn_max)
        top_layout.addWidget(self.btn_close)
        self.top_bar.setVisible(self.cfg.get("show_window_controls", True))
        main_layout.addWidget(self.top_bar)
        self.stack = QStackedWidget()
        main_layout.addWidget(self.stack)
        self.term_view = TerminalView(self, self.cfg)
        self.stack.addWidget(self.term_view)
        self.setContextMenuPolicy(Qt.NoContextMenu)
        self.rgb_timer = QTimer(self)
        self.rgb_timer.timeout.connect(self._animate_rgb)
        if self.cfg.get("rgb_mode", False):
            self.rgb_timer.start(50)
        self.shortcut_f11 = QShortcut(QKeySequence(Qt.Key_F11), self)
        self.shortcut_f11.activated.connect(self.toggle_fullscreen)

        self.term_view.term.idle_timer.start()

    def mouseMoveEvent(self, event):
        self.term_view.term._exit_eco_mode()
        super().mouseMoveEvent(event)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.top_bar.setVisible(self.cfg.get("show_window_controls", True))
        else:
            self.showFullScreen()
            self.top_bar.hide()

        self._update_blur()
        QTimer.singleShot(40, self.term_view._do_force_resize)

    def toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
            self.btn_max.setText("□")
        else:
            self.showMaximized()
            self.btn_max.setText("❐")

        self._update_blur()
        QTimer.singleShot(40, self.term_view._do_force_resize)

    def register_settings_view(self, view):
        self._settings_view = view

    def _animate_switch(self, target_widget):
        effect = QGraphicsOpacityEffect(target_widget)
        target_widget.setGraphicsEffect(effect)
        self.anim = QPropertyAnimation(effect, b"opacity")
        self.anim.setDuration(300)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setEasingCurve(QEasingCurve.OutBack)
        self.stack.setCurrentWidget(target_widget)
        self.anim.start()

    def show_terminal(self):
        self._animate_switch(self.term_view)
        QTimer.singleShot(100, self.term_view._do_force_resize)
        self.term_view.term.setFocus()

    def show_settings(self):
        if not hasattr(self, "_settings_view") or self._settings_view is None:
            self._settings_view = SettingsView(self, self.cfg)
            self.stack.addWidget(self._settings_view)
        self._animate_switch(self._settings_view)

    def show_custom_context_menu(self, global_pos):
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background-color: #1a1a1a; color: #ccc; border: 1px solid rgba(255,255,255,0.2); } QMenu::item:selected { background-color: rgba(255,255,255,0.1); color: white; }")
        action_customize = QAction("кастомизация", self)
        action_customize.triggered.connect(self.show_settings)
        menu.addAction(action_customize)
        if not self.cfg.get("show_window_controls", True):
            menu.addSeparator()
            action_exit = QAction("выход (Alt+F4)", self)
            action_exit.triggered.connect(self.close)
            menu.addAction(action_exit)
        menu.exec(global_pos)

    def _on_slider(self, val):
        self.cfg["blur_level"] = val
        self._update_blur()
        save_config(self.cfg)

    def _choose_tint(self):
        dialog = ColorPickerDialog(QColor(*self.cfg.get("tint_rgb", [20, 20, 25])), self)
        if dialog.exec():
            color = dialog.get_color()
            self.cfg["tint_rgb"] = [color.red(), color.green(), color.blue()]
            save_config(self.cfg)
            self._update_blur()
            if hasattr(self, "_settings_view") and self._settings_view:
                self._settings_view.sync_colors()
            QTimer.singleShot(50, self.term_view._do_force_resize)

    def _choose_border(self):
        bc = self.cfg.get("border_color", [255, 255, 255, 80])
        dialog = ColorPickerDialog(QColor(*bc[:3]), self)
        if dialog.exec():
            color = dialog.get_color()
            self.cfg["border_color"] = [color.red(), color.green(), color.blue(), bc[3]]
            self.cfg["rgb_mode"] = False
            save_config(self.cfg)
            if hasattr(self, "_settings_view") and self._settings_view:
                self._settings_view.chk_rgb.setChecked(False)
                self._settings_view.sync_colors()
            self.update()
            QTimer.singleShot(50, self.term_view._do_force_resize)

    def _toggle_rgb(self, state):
        self.cfg["rgb_mode"] = (state == Qt.Checked.value)
        save_config(self.cfg)
        if self.cfg["rgb_mode"]:
            self.rgb_timer.start(50)
        else:
            self.rgb_timer.stop()
            self.cfg["border_color"] = [255, 255, 255, 80]
            save_config(self.cfg)
            if hasattr(self, "_settings_view") and self._settings_view:
                self._settings_view.sync_colors()
            self.update()

    def _animate_rgb(self):
        if not self.isVisible() or not self.cfg.get("rgb_mode"):
            return
        self._hue = (getattr(self, "_hue", 0) + 0.005) % 1.0
        colorsys.hsv_to_rgb(self._hue, 0.5, 1.0)
        self.update()

    def _update_blur(self):
        if not self.isVisible():
            return

        eco = self.cfg.get("opt_eco_mode", False)
        disable_blur = self.cfg.get("opt_disable_blur", True)
        blur_bg = self.cfg.get("opt_blur_bg", True)

        if eco and disable_blur:
            try:
                self.windowEffect.setAeroEffect(int(self.winId()))
            except Exception:
                pass
            return

        if not blur_bg:
            try:
                self.windowEffect.setAeroEffect(int(self.winId()))
            except Exception:
                pass
            return

        level = self.cfg.get("blur_level", 50)
        if level >= 100 or self.isMaximized() or self.isFullScreen():
            try:
                self.windowEffect.setAeroEffect(int(self.winId()))
            except Exception:
                pass
            return

        alpha = int(255 * (1.0 - level / 100.0))
        alpha = max(1, min(255, alpha))
        hex_alpha = f"{alpha:02X}"
        r, g, b = self.cfg.get("tint_rgb", [20, 20, 25])
        hex_rgb = f"{r:02X}{g:02X}{b:02X}"
        self.windowEffect.setAcrylicEffect(
            int(self.winId()),
            gradientColor=f"{hex_rgb}{hex_alpha}",
            enableShadow=False
        )

    def showEvent(self, e):
        super().showEvent(e)
        self._update_blur()
        self.show_terminal()
        try:
            hwnd = int(self.winId())
            GWL_STYLE = -16
            WS_MAXIMIZEBOX = 0x00010000
            WS_THICKFRAME = 0x00040000
            WS_CAPTION = 0x00C00000
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_STYLE, style | WS_MAXIMIZEBOX | WS_THICKFRAME | WS_CAPTION)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd),
                33,
                ctypes.byref(ctypes.c_int(2)),
                ctypes.sizeof(ctypes.c_int)
            )
        except Exception:
            pass

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.windowHandle().startSystemMove()
            e.accept()

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing)
            if not self.isFullScreen():
                rect = self.rect().adjusted(1, 1, -1, -1)
                if self.cfg.get("rgb_mode"):
                    r, g, b = colorsys.hsv_to_rgb(getattr(self, "_hue", 0), 0.5, 1.0)
                    color = QColor(int(r * 255), int(g * 255), int(b * 255), 100)
                else:
                    bc = self.cfg.get("border_color", [255, 255, 255, 80])
                    color = QColor(*bc)
                p.setPen(QPen(color, 1))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(rect, 8, 8)

            path = QPainterPath()
            path.addRoundedRect(self.rect().adjusted(0,0,-1,-1), 8, 8)
            self.setMask(QRegion(path.toFillPolygon().toPolygon()))
        finally:
            p.end()

    def closeEvent(self, event):
        self.term_view.term.stop_pty()
        super().closeEvent(event)


if __name__ == "__main__":
    if getattr(sys, "frozen", False):
        _self_install_and_relaunch()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = Window()
    w.show()
    sys.exit(app.exec())
