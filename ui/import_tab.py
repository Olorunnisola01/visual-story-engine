"""
Import Tab — select a folder of images and paste matching prompts.
"""

import re
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QLineEdit, QTextEdit, QFileDialog,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from ui import theme

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif"}

PROMPT_HINT = (
    "Paste one prompt per line — or separate blocks with a blank line.\n\n"
    "Example:\n"
    "A misty mountain at sunrise\n\n"
    "Golden wheat fields under a stormy sky\n\n"
    "A quiet coastal village at dusk"
)


def _natural_key(p: Path):
    parts = re.split(r"(\d+)", p.stem.lower())
    return [int(x) if x.isdigit() else x for x in parts]


def scan_images(folder: str) -> list[Path]:
    d = Path(folder)
    if not d.is_dir():
        return []
    files = [f for f in d.iterdir() if f.suffix.lower() in IMAGE_EXTS]
    return sorted(files, key=_natural_key)


def parse_prompts(text: str) -> list[str]:
    blocks = [b.strip() for b in re.split(r"\n[ \t]*\n", text.strip()) if b.strip()]
    if len(blocks) > 1:
        return blocks
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _card_frame(parent: QWidget, title: str) -> tuple["QFrame", "QWidget"]:
    outer = QFrame(parent)
    outer.setStyleSheet(f"""
        QFrame {{
            background: {theme.CARD_BG};
            border: 1px solid {theme.CARD_BORDER};
            border-radius: {theme.RADIUS_MD}px;
        }}
        QLabel {{ border: none; background: transparent; }}
        QPushButton {{ border: 1px solid {theme.BTN_SECONDARY_BORDER}; }}
        QLineEdit {{ border: 1px solid {theme.INPUT_BORDER}; }}
    """)
    vl = QVBoxLayout(outer)
    vl.setContentsMargins(0, 0, 0, 0)
    vl.setSpacing(0)

    lbl = QLabel(title, outer)
    lbl.setFont(QFont(theme.FONT_FAMILY, theme.FONT_SIZE_XS, QFont.Weight.Bold))
    lbl.setStyleSheet(f"color: {theme.SECTION_LABEL_TEXT}; padding: 10px 16px 6px;")
    vl.addWidget(lbl)

    sep = QFrame(outer)
    sep.setFixedHeight(1)
    sep.setStyleSheet(f"background: {theme.BORDER};")
    vl.addWidget(sep)

    inner = QWidget(outer)
    inner.setStyleSheet("background: transparent;")
    vl.addWidget(inner, stretch=1)
    return outer, inner


class ImportTab(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self._images: list[Path] = []
        self._hint_active = True
        self._build()

    def _build(self):
        vl = QVBoxLayout(self)
        vl.setContentsMargins(16, 16, 16, 16)
        vl.setSpacing(12)

        # ── Image folder card ──────────────────────────────────────────────
        img_outer, img_inner = _card_frame(self, "IMAGE FOLDER")
        il = QVBoxLayout(img_inner)
        il.setContentsMargins(16, 10, 16, 12)
        il.setSpacing(6)

        row = QWidget()
        row.setStyleSheet("background: transparent;")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)

        flbl = QLabel("Folder")
        flbl.setFixedWidth(56)
        flbl.setFont(QFont(theme.FONT_FAMILY, theme.FONT_SIZE_BASE))
        flbl.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        rl.addWidget(flbl)

        self._folder_entry = QLineEdit()
        self._folder_entry.setPlaceholderText("Select folder containing generated images…")
        self._folder_entry.setFont(QFont(theme.FONT_FAMILY, theme.FONT_SIZE_BASE))
        self._folder_entry.setStyleSheet(f"""
            background: {theme.INPUT_BG}; border: 1px solid {theme.INPUT_BORDER};
            border-radius: {theme.RADIUS_SM}px; padding: 6px 10px; color: {theme.INPUT_TEXT};
        """)
        self._folder_entry.textChanged.connect(self._on_folder_changed)
        rl.addWidget(self._folder_entry, stretch=1)

        browse_btn = QPushButton("Browse")
        browse_btn.setFixedWidth(84)
        browse_btn.setStyleSheet(f"""
            QPushButton {{ background: {theme.BTN_SECONDARY_BG}; color: {theme.BTN_SECONDARY_TEXT};
                border: 1px solid {theme.BTN_SECONDARY_BORDER}; border-radius: {theme.RADIUS_SM}px;
                padding: 6px 14px; font-size: 12px; }}
            QPushButton:hover {{ background: {theme.BTN_SECONDARY_HOVER}; }}
        """)
        browse_btn.clicked.connect(self._browse_folder)
        rl.addWidget(browse_btn)

        il.addWidget(row)

        self._img_status = QLabel("No folder selected")
        self._img_status.setFont(QFont(theme.FONT_FAMILY, theme.FONT_SIZE_SM))
        self._img_status.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        il.addWidget(self._img_status)

        vl.addWidget(img_outer)

        # ── Prompts card ───────────────────────────────────────────────────
        prompt_outer = QFrame()
        prompt_outer.setStyleSheet(f"""
            QFrame {{
                background: {theme.CARD_BG};
                border: 1px solid {theme.CARD_BORDER};
                border-radius: {theme.RADIUS_MD}px;
            }}
            QLabel {{ border: none; background: transparent; }}
        """)
        pv = QVBoxLayout(prompt_outer)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(0)

        ph = QWidget()
        ph.setStyleSheet("background: transparent;")
        phl = QHBoxLayout(ph)
        phl.setContentsMargins(16, 10, 16, 6)

        ptitle = QLabel("PROMPTS")
        ptitle.setFont(QFont(theme.FONT_FAMILY, theme.FONT_SIZE_XS, QFont.Weight.Bold))
        ptitle.setStyleSheet(f"color: {theme.SECTION_LABEL_TEXT};")
        phl.addWidget(ptitle)
        phl.addStretch()

        self._prompt_count_lbl = QLabel("0 prompts")
        self._prompt_count_lbl.setFont(QFont(theme.FONT_FAMILY, theme.FONT_SIZE_SM))
        self._prompt_count_lbl.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        phl.addWidget(self._prompt_count_lbl)
        phl.addSpacing(12)

        import_btn = QPushButton("Import from .txt")
        import_btn.setFixedWidth(130)
        import_btn.setStyleSheet(f"""
            QPushButton {{ background: {theme.BTN_SECONDARY_BG}; color: {theme.BTN_SECONDARY_TEXT};
                border: 1px solid {theme.BTN_SECONDARY_BORDER}; border-radius: {theme.RADIUS_SM}px;
                padding: 5px 12px; font-size: 12px; }}
            QPushButton:hover {{ background: {theme.BTN_SECONDARY_HOVER}; }}
        """)
        import_btn.clicked.connect(self._import_txt)
        phl.addWidget(import_btn)
        pv.addWidget(ph)

        sep2 = QFrame()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet(f"background: {theme.BORDER};")
        pv.addWidget(sep2)

        self._prompt_box = QTextEdit()
        self._prompt_box.setFont(QFont("Consolas", theme.FONT_SIZE_BASE))
        self._prompt_box.setPlainText(PROMPT_HINT)
        self._prompt_box.setStyleSheet(f"""
            QTextEdit {{
                background: {theme.BG_ELEVATED}; border: none;
                border-bottom-left-radius: {theme.RADIUS_MD}px;
                border-bottom-right-radius: {theme.RADIUS_MD}px;
                padding: 12px; color: {theme.INPUT_PLACEHOLDER};
            }}
        """)
        self._prompt_box.textChanged.connect(self._on_prompt_changed)

        # Monkey-patch focus events for hint behaviour
        orig_in  = self._prompt_box.focusInEvent
        orig_out = self._prompt_box.focusOutEvent

        def focus_in(ev):
            if self._hint_active:
                self._prompt_box.clear()
                self._prompt_box.setStyleSheet(
                    self._prompt_box.styleSheet().replace(
                        theme.INPUT_PLACEHOLDER, theme.INPUT_TEXT
                    )
                )
                self._hint_active = False
            orig_in(ev)

        def focus_out(ev):
            if not self._prompt_box.toPlainText().strip():
                self._hint_active = True
                self._prompt_box.setPlainText(PROMPT_HINT)
                self._prompt_box.setStyleSheet(
                    self._prompt_box.styleSheet().replace(
                        theme.INPUT_TEXT, theme.INPUT_PLACEHOLDER
                    )
                )
                self._update_counts()
            orig_out(ev)

        self._prompt_box.focusInEvent  = focus_in   # type: ignore[method-assign]
        self._prompt_box.focusOutEvent = focus_out  # type: ignore[method-assign]

        pv.addWidget(self._prompt_box, stretch=1)
        vl.addWidget(prompt_outer, stretch=1)

        # ── Action bar ─────────────────────────────────────────────────────
        action = QFrame()
        action.setStyleSheet(f"""
            QFrame {{
                background: {theme.CARD_BG};
                border: 1px solid {theme.CARD_BORDER};
                border-radius: {theme.RADIUS_MD}px;
            }}
            QLabel {{ border: none; background: transparent; }}
        """)
        al = QHBoxLayout(action)
        al.setContentsMargins(16, 12, 16, 12)
        al.setSpacing(12)

        self._match_label = QLabel("Select a folder and add prompts to begin")
        self._match_label.setFont(QFont(theme.FONT_FAMILY, theme.FONT_SIZE_BASE))
        self._match_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        al.addWidget(self._match_label, stretch=1)

        self._load_btn = QPushButton("Load into Gallery  →")
        self._load_btn.setFixedWidth(180)
        self._load_btn.setFixedHeight(36)
        self._load_btn.setEnabled(False)
        self._load_btn.setStyleSheet(f"""
            QPushButton {{ background: {theme.BTN_PRIMARY_BG}; color: {theme.BTN_PRIMARY_TEXT};
                border: none; border-radius: {theme.RADIUS_SM}px;
                padding: 8px 18px; font-weight: bold; font-size: 13px; }}
            QPushButton:hover {{ background: {theme.BTN_PRIMARY_HOVER}; }}
            QPushButton:disabled {{ background: {theme.BTN_DISABLED_BG}; color: {theme.BTN_DISABLED_TEXT}; }}
        """)
        self._load_btn.clicked.connect(self._load_gallery)
        al.addWidget(self._load_btn)
        vl.addWidget(action)

        # Initial scan
        if self.app.config.get("last_image_dir"):
            self._folder_entry.setText(self.app.config["last_image_dir"])

    # ── Folder ─────────────────────────────────────────────────────────────
    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select image folder",
                                                  self._folder_entry.text() or "")
        if folder:
            self._folder_entry.setText(folder)

    def _on_folder_changed(self, folder: str):
        self.app.config["last_image_dir"] = folder
        self.app.save_settings()
        self._scan_folder(folder)

    def _scan_folder(self, folder: str):
        self._images = scan_images(folder)
        n = len(self._images)
        if n == 0:
            self._img_status.setText("No images found (supported: JPG PNG WEBP BMP TIFF)")
            self._img_status.setStyleSheet(f"color: {theme.DANGER};")
        else:
            names = ", ".join(p.name for p in self._images[:3])
            suffix = f" … +{n-3} more" if n > 3 else ""
            self._img_status.setText(
                f"{n} image{'s' if n != 1 else ''} found: {names}{suffix}"
            )
            self._img_status.setStyleSheet(f"color: {theme.SUCCESS};")
        self._update_counts()

    # ── Txt import ─────────────────────────────────────────────────────────
    def _import_txt(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import prompts", "", "Text files (*.txt);;All files (*.*)"
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
            self._hint_active = False
            self._prompt_box.setStyleSheet(
                self._prompt_box.styleSheet().replace(theme.INPUT_PLACEHOLDER, theme.INPUT_TEXT)
            )
            self._prompt_box.setPlainText(text)
            self._update_counts()
        except Exception as e:
            self.app.set_status(f"⚠ Could not read file: {e}")

    # ── Counts ─────────────────────────────────────────────────────────────
    def _on_prompt_changed(self):
        if not self._hint_active:
            self._update_counts()

    def _get_prompts(self) -> list[str]:
        return [] if self._hint_active else parse_prompts(self._prompt_box.toPlainText())

    def _update_counts(self):
        prompts = self._get_prompts()
        n_img, n_prm = len(self._images), len(prompts)

        cnt_text  = f"{n_prm} prompt{'s' if n_prm != 1 else ''}" if n_prm else "0 prompts"
        cnt_color = theme.TEXT_SECONDARY if n_prm else theme.TEXT_MUTED
        self._prompt_count_lbl.setText(cnt_text)
        self._prompt_count_lbl.setStyleSheet(f"color: {cnt_color};")

        self._load_btn.setEnabled(n_img > 0 and n_prm > 0)

        if n_img == 0 and n_prm == 0:
            msg, color = "Select a folder and add prompts to begin", theme.TEXT_MUTED
        elif n_img == 0:
            msg, color = "Select an image folder", theme.TEXT_MUTED
        elif n_prm == 0:
            msg, color = f"{n_img} images loaded — add prompts", theme.TEXT_MUTED
        elif n_img == n_prm:
            msg, color = f"✓  {n_img} images matched to {n_prm} prompts — ready", theme.SUCCESS
        elif n_img > n_prm:
            diff = n_img - n_prm
            msg  = f"⚠  {n_img} images / {n_prm} prompts — {diff} image{'s' if diff>1 else ''} will have no prompt"
            color = theme.WARNING
        else:
            diff = n_prm - n_img
            msg  = f"⚠  {n_img} images / {n_prm} prompts — last {diff} prompt{'s' if diff>1 else ''} ignored"
            color = theme.WARNING

        self._match_label.setText(msg)
        self._match_label.setStyleSheet(f"color: {color};")

    # ── Load ────────────────────────────────────────────────────────────────
    def _load_gallery(self):
        prompts = self._get_prompts()
        pairs = [
            (self._images[i], prompts[i] if i < len(prompts) else "")
            for i in range(len(self._images))
        ]
        if not pairs:
            self.app.set_status("⚠ Nothing to load — select a folder with images")
            return
        self.app.set_status(f"✓ {len(pairs)} images loaded into Gallery")
        self.app.emit("images_loaded", pairs)
