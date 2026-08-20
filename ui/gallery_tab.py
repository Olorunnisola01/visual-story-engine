from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QFrame, QPushButton, QScrollArea,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap, QImage

from PIL import Image

from ui import theme


def _pil_to_pixmap(img: Image.Image) -> QPixmap:
    img = img.convert("RGB")
    data = img.tobytes("raw", "RGB")
    qimg = QImage(data, img.width, img.height, img.width * 3,
                  QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg)


class GalleryTab(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self._pairs: list[tuple[Path, str]] = []
        self._build()

    def _build(self):
        vl = QVBoxLayout(self)
        vl.setContentsMargins(16, 16, 16, 16)
        vl.setSpacing(12)

        # ── Header ─────────────────────────────────────────────────────────
        header = QFrame()
        header.setStyleSheet(f"""
            QFrame {{
                background: {theme.CARD_BG};
                border: 1px solid {theme.CARD_BORDER};
                border-radius: {theme.RADIUS_MD}px;
            }}
            QLabel {{ border: none; background: transparent; }}
        """)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 10, 16, 10)
        hl.setSpacing(12)

        title_lbl = QLabel("GALLERY")
        title_lbl.setFont(QFont(theme.FONT_FAMILY, theme.FONT_SIZE_XS, QFont.Weight.Bold))
        title_lbl.setStyleSheet(f"color: {theme.SECTION_LABEL_TEXT};")
        hl.addWidget(title_lbl)

        self._count_lbl = QLabel("No images loaded")
        self._count_lbl.setFont(QFont(theme.FONT_FAMILY, theme.FONT_SIZE_SM))
        self._count_lbl.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        hl.addWidget(self._count_lbl)
        hl.addStretch()

        btn_style_sec = f"""
            QPushButton {{ background: {theme.BTN_SECONDARY_BG}; color: {theme.BTN_SECONDARY_TEXT};
                border: 1px solid {theme.BTN_SECONDARY_BORDER}; border-radius: {theme.RADIUS_SM}px;
                padding: 6px 14px; font-size: 12px; }}
            QPushButton:hover {{ background: {theme.BTN_SECONDARY_HOVER}; }}
        """

        clear_btn = QPushButton("Clear")
        clear_btn.setFixedWidth(80)
        clear_btn.setStyleSheet(btn_style_sec)
        clear_btn.clicked.connect(self._clear)
        hl.addWidget(clear_btn)

        self._compose_btn = QPushButton("Send to Compose  →")
        self._compose_btn.setFixedWidth(170)
        self._compose_btn.setEnabled(False)
        self._compose_btn.setStyleSheet(f"""
            QPushButton {{ background: {theme.BTN_PRIMARY_BG}; color: {theme.BTN_PRIMARY_TEXT};
                border: none; border-radius: {theme.RADIUS_SM}px;
                padding: 6px 14px; font-weight: bold; font-size: 12px; }}
            QPushButton:hover {{ background: {theme.BTN_PRIMARY_HOVER}; }}
            QPushButton:disabled {{ background: {theme.BTN_DISABLED_BG}; color: {theme.BTN_DISABLED_TEXT}; }}
        """)
        self._compose_btn.clicked.connect(self._go_compose)
        hl.addWidget(self._compose_btn)

        vl.addWidget(header)

        # ── Scroll area ────────────────────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setStyleSheet(f"""
            QScrollArea {{
                background: {theme.GREY_50};
                border: 1px solid {theme.CARD_BORDER};
                border-radius: {theme.RADIUS_MD}px;
            }}
        """)

        self._grid_container = QWidget()
        self._grid_container.setStyleSheet(f"background: {theme.GREY_50};")
        self._grid_layout = QGridLayout(self._grid_container)
        self._grid_layout.setSpacing(8)
        self._grid_layout.setContentsMargins(12, 12, 12, 12)
        self._grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        self._scroll.setWidget(self._grid_container)
        vl.addWidget(self._scroll, stretch=1)

        self._show_empty()

    # ── Empty state ────────────────────────────────────────────────────────
    def _show_empty(self):
        empty = QWidget()
        empty.setStyleSheet("background: transparent;")
        ev = QVBoxLayout(empty)
        ev.setAlignment(Qt.AlignmentFlag.AlignCenter)

        t = QLabel("No images yet")
        t.setFont(QFont(theme.FONT_FAMILY, 16, QFont.Weight.Bold))
        t.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ev.addWidget(t)

        s = QLabel("Go to ① Import, select your image folder and add prompts")
        s.setFont(QFont(theme.FONT_FAMILY, theme.FONT_SIZE_BASE))
        s.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ev.addWidget(s)

        self._grid_layout.addWidget(empty, 0, 0, 1, 4)

    # ── Load ───────────────────────────────────────────────────────────────
    def load_pairs(self, pairs: list[tuple[Path, str]]):
        self._clear_grid()
        self._pairs = pairs

        if not pairs:
            self._count_lbl.setText("No images loaded")
            self._count_lbl.setStyleSheet(f"color: {theme.TEXT_MUTED};")
            self._compose_btn.setEnabled(False)
            self._show_empty()
            return

        COLS = 4
        for idx, (img_path, prompt) in enumerate(pairs):
            card = self._make_card(idx + 1, img_path, prompt)
            if card:
                self._grid_layout.addWidget(card, idx // COLS, idx % COLS)

        n = len(pairs)
        self._count_lbl.setText(f"{n} image{'s' if n != 1 else ''}")
        self._count_lbl.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        self._compose_btn.setEnabled(True)

    def _make_card(self, idx: int, img_path: Path, prompt: str) -> QFrame | None:
        try:
            img = Image.open(img_path)
            img.thumbnail((200, 200))
            pixmap = _pil_to_pixmap(img)
        except Exception as e:
            print(f"Thumbnail error {img_path}: {e}")
            return None

        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background: {theme.CARD_BG};
                border: 1px solid {theme.CARD_BORDER};
                border-radius: {theme.RADIUS_MD}px;
            }}
            QLabel {{ border: none; background: transparent; }}
        """)
        card.setFixedWidth(216)

        cv = QVBoxLayout(card)
        cv.setContentsMargins(8, 8, 8, 8)
        cv.setSpacing(6)

        # Image + badge overlay
        img_container = QWidget()
        img_container.setStyleSheet("background: transparent;")
        img_container.setFixedSize(200, 200)

        img_lbl = QLabel(img_container)
        img_lbl.setPixmap(pixmap)
        img_lbl.setFixedSize(200, 200)
        img_lbl.setScaledContents(False)
        img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img_lbl.setStyleSheet("background: transparent;")

        # Number badge (top-left overlay)
        badge = QLabel(str(idx), img_container)
        badge.setFont(QFont(theme.FONT_FAMILY, theme.FONT_SIZE_XS, QFont.Weight.Bold))
        badge.setStyleSheet(f"""
            background: {theme.GREY_900}; color: {theme.WHITE};
            border-radius: 4px; padding: 1px 5px;
        """)
        badge.setFixedSize(26, 20)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.move(6, 6)

        cv.addWidget(img_container)

        short = (prompt[:44] + "…") if len(prompt) > 44 else prompt
        if not short:
            short = img_path.name
        caption = QLabel(short)
        caption.setFont(QFont(theme.FONT_FAMILY, theme.FONT_SIZE_SM))
        caption.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        caption.setWordWrap(True)
        cv.addWidget(caption)

        return card

    # ── Navigation ─────────────────────────────────────────────────────────
    def _go_compose(self):
        self.app.set_status("✓ Images sent to Compose — ready to create video")
        self.app.go_to_tab(2)

    # ── Clear ──────────────────────────────────────────────────────────────
    def _clear_grid(self):
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _clear(self):
        self._clear_grid()
        self._pairs = []
        self.app.image_prompt_pairs = []
        self._count_lbl.setText("No images loaded")
        self._count_lbl.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        self._compose_btn.setEnabled(False)
        self._show_empty()
        self.app.set_status("Gallery cleared")
