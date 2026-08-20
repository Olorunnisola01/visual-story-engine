import json
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QFrame, QTabWidget, QPushButton,
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont

from ui import theme
from ui.theme import QSS

CONFIG_PATH = Path(__file__).parent.parent / "config.json"


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"deepgram_key": "", "llm_key": "", "last_output_dir": "", "last_image_dir": ""}


def save_config(cfg: dict):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


class App(QMainWindow):
    # Thread-safe channel: background threads call self.app.emit(...) and this
    # signal marshals the call back onto the main thread automatically.
    _msg = Signal(tuple)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Visual Story Engine")
        self.resize(1160, 820)
        self.setMinimumSize(960, 660)
        self.setStyleSheet(QSS)

        self.config = load_config()
        self.image_prompt_pairs: list[tuple[Path, str]] = []
        self._active_toast: QFrame | None = None

        self._msg.connect(self._dispatch)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        self._build_header(root)
        self._build_tabs(root)
        self._build_statusbar(root)

    # ── Header ────────────────────────────────────────────────────────────────
    def _build_header(self, layout: QVBoxLayout):
        header = QFrame()
        header.setFixedHeight(62)
        header.setStyleSheet(
            f"background: {theme.WHITE}; border-bottom: 1px solid {theme.BORDER};"
        )

        h = QHBoxLayout(header)
        h.setContentsMargins(16, 0, 16, 0)
        h.setSpacing(0)

        accent = QFrame()
        accent.setFixedSize(4, 32)
        accent.setStyleSheet(f"background: {theme.GREY_900}; border-radius: 2px;")
        h.addWidget(accent)
        h.addSpacing(12)

        titles = QWidget()
        titles.setStyleSheet("background: transparent;")
        tv = QVBoxLayout(titles)
        tv.setSpacing(1)
        tv.setContentsMargins(0, 0, 0, 0)

        t_lbl = QLabel("Visual Story Engine")
        t_lbl.setFont(QFont(theme.FONT_FAMILY, theme.FONT_SIZE_LG, QFont.Weight.Bold))
        t_lbl.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; background: transparent;")
        tv.addWidget(t_lbl)

        s_lbl = QLabel("Import  ·  Curate  ·  Compose")
        s_lbl.setFont(QFont(theme.FONT_FAMILY, theme.FONT_SIZE_SM))
        s_lbl.setStyleSheet(f"color: {theme.TEXT_MUTED}; background: transparent;")
        tv.addWidget(s_lbl)

        h.addWidget(titles)
        h.addStretch()
        layout.addWidget(header)

    # ── Tabs ──────────────────────────────────────────────────────────────────
    def _build_tabs(self, layout: QVBoxLayout):
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(False)
        self.tabs.setContentsMargins(16, 10, 16, 0)
        layout.addWidget(self.tabs, stretch=1)

        from ui.import_tab import ImportTab
        from ui.gallery_tab import GalleryTab
        from ui.video_tab import VideoTab

        self.import_tab  = ImportTab(self)
        self.gallery_tab = GalleryTab(self)
        self.video_tab   = VideoTab(self)

        self.tabs.addTab(self.import_tab,  "① Import")
        self.tabs.addTab(self.gallery_tab, "② Gallery")
        self.tabs.addTab(self.video_tab,   "③ Compose")

    # ── Status bar ────────────────────────────────────────────────────────────
    def _build_statusbar(self, layout: QVBoxLayout):
        bar = QFrame()
        bar.setFixedHeight(30)
        bar.setStyleSheet(
            f"background: {theme.GREY_50}; border-top: 1px solid {theme.BORDER};"
        )
        h = QHBoxLayout(bar)
        h.setContentsMargins(14, 0, 14, 0)
        h.setSpacing(6)

        self._status_dot = QLabel("●")
        self._status_dot.setFont(QFont(theme.FONT_FAMILY, 9))
        self._status_dot.setStyleSheet(
            f"color: {theme.SUCCESS}; background: transparent;"
        )
        h.addWidget(self._status_dot)

        self._status_label = QLabel("Ready")
        self._status_label.setFont(QFont(theme.FONT_FAMILY, theme.FONT_SIZE_SM))
        self._status_label.setStyleSheet(
            f"color: {theme.TEXT_SECONDARY}; background: transparent;"
        )
        h.addWidget(self._status_label)
        h.addStretch()
        layout.addWidget(bar)

    # ── Message dispatch ──────────────────────────────────────────────────────
    def _dispatch(self, msg: tuple):
        kind = msg[0]
        if kind == "status":
            self._update_status(msg[1])
        elif kind == "images_loaded":
            pairs = msg[1]
            self.image_prompt_pairs = pairs
            self.gallery_tab.load_pairs(pairs)
            self.video_tab.set_image_pairs(pairs)
            self.go_to_tab(1)
        elif kind == "video_done":
            self.video_tab.on_video_done(msg[1])
        elif kind == "video_error":
            self.video_tab.on_video_error(msg[1])
        elif kind == "video_progress":
            self.video_tab.on_video_progress(msg[1])

    def _update_status(self, text: str):
        self._status_label.setText(text)
        low = text.lower()
        if any(w in low for w in ("error", "failed", "fail", "⚠")):
            color = theme.DANGER
        elif any(w in low for w in ("done", "saved", "complete", "✓", "ready", "loaded")):
            color = theme.SUCCESS
        elif any(w in low for w in ("creating", "stitching", "transcrib", "analysing")):
            color = theme.WARNING
        else:
            color = theme.SUCCESS
        self._status_dot.setStyleSheet(f"color: {color}; background: transparent;")

    # ── Public API ────────────────────────────────────────────────────────────
    def go_to_tab(self, index: int):
        QTimer.singleShot(10, lambda: self.tabs.setCurrentIndex(index))

    def emit(self, *args):
        """Call from any thread — safely dispatches to the main thread."""
        self._msg.emit(args)

    def set_status(self, text: str):
        self.emit("status", text)

    def save_settings(self):
        save_config(self.config)

    # ── Toast notification ────────────────────────────────────────────────────
    def show_toast(self, title: str, detail: str = "", duration_ms: int = 4500):
        if self._active_toast:
            try:
                self._active_toast.deleteLater()
            except Exception:
                pass
            self._active_toast = None

        toast = QFrame(self)
        toast.setStyleSheet(f"""
            QFrame {{
                background: {theme.GREY_900};
                border: 1px solid #374151;
                border-radius: 10px;
            }}
            QLabel {{ background: transparent; }}
        """)
        self._active_toast = toast

        vl = QVBoxLayout(toast)
        vl.setContentsMargins(16, 10, 44, 10)
        vl.setSpacing(2)

        t_lbl = QLabel(title)
        t_lbl.setFont(QFont(theme.FONT_FAMILY, 14, QFont.Weight.Bold))
        t_lbl.setStyleSheet(f"color: {theme.WHITE};")
        vl.addWidget(t_lbl)

        if detail:
            short = detail if len(detail) <= 70 else "…" + detail[-68:]
            d_lbl = QLabel(short)
            d_lbl.setFont(QFont(theme.FONT_FAMILY, theme.FONT_SIZE_SM))
            d_lbl.setStyleSheet("color: #9CA3AF;")
            vl.addWidget(d_lbl)

        close_btn = QPushButton("×", toast)
        close_btn.setFixedSize(26, 26)
        close_btn.setStyleSheet("""
            QPushButton {
                background: transparent; color: white;
                border: none; font-size: 16px; font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:hover { background: #374151; }
        """)
        close_btn.clicked.connect(toast.deleteLater)

        tw, th = 520, (72 if detail else 50)
        tx = (self.width() - tw) // 2
        ty = self.height() - th - 50
        toast.setGeometry(tx, ty, tw, th)
        close_btn.move(tw - 34, 10)

        toast.raise_()
        toast.show()
        QTimer.singleShot(duration_ms, lambda: self._dismiss_toast(toast))

    def _dismiss_toast(self, toast: QFrame):
        try:
            toast.deleteLater()
        except Exception:
            pass
        if self._active_toast is toast:
            self._active_toast = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._active_toast:
            tw = 520
            th = self._active_toast.height()
            tx = (self.width() - tw) // 2
            ty = self.height() - th - 50
            try:
                self._active_toast.move(tx, ty)
            except Exception:
                pass
