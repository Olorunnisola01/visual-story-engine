import os
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFrame,
    QPushButton, QLineEdit, QTextEdit, QScrollArea, QComboBox, QProgressBar,
    QSlider, QFileDialog, QRadioButton, QCheckBox, QButtonGroup, QSpinBox,
    QColorDialog,
)
from PySide6.QtCore import Qt, Signal, QThread, QTimer
from PySide6.QtGui import QFont, QFontDatabase, QColor, QPixmap, QPainter

from video.stitcher import TRANSITIONS, stitch_video, get_audio_duration
from video.transcribe import (
    transcribe_audio, split_words_into_segments,
    parse_manual_transcript, split_by_semantic_alignment,
    split_by_llm_alignment, build_segments_from_prompt_timestamps,
)
from video.captions import build_ass_file, render_preview_frame
from ui.import_tab import _natural_key

GROQ_BASE        = "https://api.groq.com/openai/v1"
GROQ_MODEL       = "llama-3.3-70b-versatile"
OPENROUTER_BASE  = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "meta-llama/llama-3.3-70b-instruct"
OPENAI_BASE      = "https://api.openai.com/v1"
OPENAI_MODEL     = "gpt-4o-mini"
from ui import theme


# ── Background worker ─────────────────────────────────────────────────────────

class _VideoWorker(QThread):
    progress = Signal(str)
    done     = Signal(str)
    error    = Signal(str)

    def __init__(self, **kwargs):
        super().__init__()
        for k, v in kwargs.items():
            setattr(self, f"_{k}", v)

    def run(self):
        try:
            # Preserve the order images were paired with prompts in — do NOT
            # re-sort here. A lexicographic sort would put "image10" before
            # "image2", desyncing every image from the prompt it was matched to.
            images    = list(self._images)
            audio     = Path(self._audio)
            output    = Path(self._output)
            n         = len(images)
            mode      = self._timing_mode
            dg_key    = self._dg_key
            tm        = self._trans_mode
            tc        = self._trans_choice
            ratio     = self._ratio
            trans_dur = self._trans_dur
            zoom_mode = self._zoom_mode
            zoom_int  = self._zoom_intensity
            prompts   = self._prompts
            llm_key   = self._llm_key
            llm_base  = self._llm_base
            llm_model = self._llm_model

            self.progress.emit("Analysing audio…")
            audio_dur = get_audio_duration(audio)
            words = None  # word-level transcript, filled in if computed below

            if mode in ("smart_deepgram", "smart_manual"):
                # Embedded prompt timestamps take priority within Smart modes —
                # deterministic, no transcription or alignment guessing needed.
                segments = None
                if prompts and len(prompts) == n:
                    self.progress.emit("Checking prompts for embedded timestamps…")
                    segments = build_segments_from_prompt_timestamps(
                        prompts, audio_dur, llm_key, llm_base, llm_model
                    )
                    if segments:
                        self.progress.emit("Using timestamps embedded in prompts — no transcription needed.")

                if segments is None:
                    if mode == "smart_deepgram":
                        self.progress.emit("Transcribing with Deepgram…")
                        words = transcribe_audio(audio, dg_key)
                    else:
                        self.progress.emit("Parsing manual transcript…")
                        words = parse_manual_transcript(self._manual_transcript, audio_dur)

                    if prompts and len(prompts) == n and llm_key:
                        self.progress.emit("Aligning images to narration via LLM…")
                        segments = split_by_llm_alignment(
                            words, n, prompts, llm_key, llm_base, llm_model
                        )
                    elif prompts and len(prompts) == n:
                        self.progress.emit("Running semantic alignment (sentence embeddings)…")
                        segments = split_by_semantic_alignment(words, n, prompts)
                    else:
                        segments = split_words_into_segments(words, n)

                    # Scale to fill exact audio duration (embedded timestamps
                    # are already exact and must NOT be rescaled)
                    total = sum(s["duration"] for s in segments)
                    if total > 0 and abs(total - audio_dur) > 0.01:
                        scale = audio_dur / total
                        cum = 0.0
                        scaled = []
                        for s in segments:
                            d = s["duration"] * scale
                            scaled.append({"start": cum, "end": cum + d, "duration": d})
                            cum += d
                        segments = scaled
            else:
                d = audio_dur / n
                cum = 0.0
                segments = []
                for _ in range(n):
                    segments.append({"start": cum, "end": cum + d, "duration": d})
                    cum += d

            captions_ass_path = None
            if getattr(self, "_captions_enabled", False):
                if words is None:
                    # Equal/Fixed timing modes never transcribe — captions
                    # need word-level timestamps regardless, so get them now.
                    if dg_key:
                        self.progress.emit("Transcribing for captions…")
                        words = transcribe_audio(audio, dg_key)
                    elif getattr(self, "_manual_transcript", ""):
                        self.progress.emit("Parsing manual transcript for captions…")
                        words = parse_manual_transcript(self._manual_transcript, audio_dur)
                    else:
                        raise ValueError(
                            "Captions need either a Deepgram API key or a pasted "
                            "manual transcript to get word timing."
                        )
                cap_w, cap_h = (1920, 1080) if ratio == "16:9" else (1080, 1920)
                self.progress.emit("Building caption file…")
                captions_ass_path = Path(tempfile.gettempdir()) / f"vse_captions_{os.getpid()}.ass"
                build_ass_file(
                    words, captions_ass_path, cap_w, cap_h,
                    font_family=self._cap_font, font_size=self._cap_size,
                    text_color=self._cap_text_color, highlight_color=self._cap_highlight_color,
                    outline_color=self._cap_outline_color, outline_width=self._cap_outline_width,
                    position=self._cap_position, margin_v=self._cap_margin,
                    bold=self._cap_bold,
                )

            self.progress.emit("Stitching with FFmpeg…")
            try:
                stitch_video(
                    image_paths=images, audio_path=audio, output_path=output,
                    segments=segments, transition_mode=tm, transition_choice=tc,
                    aspect_ratio=ratio, transition_duration=trans_dur,
                    zoom_mode=zoom_mode, zoom_intensity=zoom_int,
                    audio_duration=audio_dur,
                    captions_ass_path=captions_ass_path,
                    on_progress=self.progress.emit,
                )
            finally:
                if captions_ass_path:
                    try:
                        os.unlink(captions_ass_path)
                    except OSError:
                        pass
            self.done.emit(str(output))
        except Exception as e:
            self.error.emit(str(e))


# ── Caption preview worker ────────────────────────────────────────────────────

class _CaptionPreviewWorker(QThread):
    """
    Renders one still frame through the real FFmpeg + libass pipeline so the
    live caption preview is pixel-identical to the final burned-in captions,
    not a Qt-drawn approximation. Runs off the UI thread so tweaking a
    slider never freezes the window.
    """
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, **kwargs):
        super().__init__()
        self._kwargs = kwargs

    def run(self):
        try:
            path = render_preview_frame(**self._kwargs)
            self.done.emit(str(path))
        except Exception as e:
            self.failed.emit(str(e))


# ── Style helpers ─────────────────────────────────────────────────────────────

def _sec_btn(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setStyleSheet(f"""
        QPushButton {{ background: {theme.BTN_SECONDARY_BG}; color: {theme.BTN_SECONDARY_TEXT};
            border: 1px solid {theme.BTN_SECONDARY_BORDER}; border-radius: {theme.RADIUS_SM}px;
            padding: 6px 14px; font-size: 12px; }}
        QPushButton:hover {{ background: {theme.BTN_SECONDARY_HOVER}; }}
    """)
    return btn


def _lbl(text: str, w: int = 100, font_size: int = theme.FONT_SIZE_BASE,
         color: str = theme.TEXT_SECONDARY) -> QLabel:
    l = QLabel(text)
    if w:
        l.setFixedWidth(w)
    l.setFont(QFont(theme.FONT_FAMILY, font_size))
    l.setStyleSheet(f"color: {color}; background: transparent;")
    return l


def _entry(placeholder: str = "") -> QLineEdit:
    e = QLineEdit()
    if placeholder:
        e.setPlaceholderText(placeholder)
    e.setFont(QFont(theme.FONT_FAMILY, theme.FONT_SIZE_BASE))
    e.setStyleSheet(f"""
        background: {theme.INPUT_BG}; color: {theme.INPUT_TEXT};
        border: 1px solid {theme.INPUT_BORDER}; border-radius: {theme.RADIUS_SM}px;
        padding: 6px 10px;
    """)
    return e


def _card(parent: QWidget, title: str) -> tuple[QFrame, QWidget]:
    outer = QFrame(parent)
    outer.setStyleSheet(f"""
        QFrame {{
            background: {theme.CARD_BG};
            border: 1px solid {theme.CARD_BORDER};
            border-radius: {theme.RADIUS_MD}px;
        }}
        QLabel {{ background: transparent; border: none; }}
        QCheckBox {{ background: transparent; }}
        QRadioButton {{ background: transparent; }}
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
    vl.addWidget(inner)
    return outer, inner


def _radio(text: str, group: QButtonGroup) -> QRadioButton:
    rb = QRadioButton(text)
    rb.setFont(QFont(theme.FONT_FAMILY, theme.FONT_SIZE_BASE))
    rb.setStyleSheet(f"""
        QRadioButton {{ color: {theme.TEXT_PRIMARY}; spacing: 8px; }}
        QRadioButton::indicator {{
            width: 16px; height: 16px;
            border-radius: 8px; border: 2px solid {theme.BORDER_STRONG};
            background: {theme.WHITE};
        }}
        QRadioButton::indicator:checked {{
            background: {theme.ACCENT}; border-color: {theme.ACCENT};
        }}
    """)
    group.addButton(rb)
    return rb


# ── Main tab widget ───────────────────────────────────────────────────────────

class VideoTab(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self._image_paths: list[Path] = []
        self._manual_cuts: list[str] = []
        self._worker: _VideoWorker | None = None
        self._build()

    def _build(self):
        outer_vl = QVBoxLayout(self)
        outer_vl.setContentsMargins(0, 0, 0, 0)
        outer_vl.setSpacing(0)

        # Scrollable form
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        container = QWidget()
        container.setStyleSheet(f"background: {theme.WHITE};")
        form = QVBoxLayout(container)
        form.setContentsMargins(16, 16, 16, 8)
        form.setSpacing(12)

        scroll.setWidget(container)
        outer_vl.addWidget(scroll, stretch=1)

        # ── Source Files ───────────────────────────────────────────────────
        src_outer, src = _card(container, "SOURCE FILES")
        src_gl = QGridLayout(src)
        src_gl.setContentsMargins(16, 10, 16, 12)
        src_gl.setSpacing(8)
        src_gl.setColumnStretch(1, 1)

        src_gl.addWidget(_lbl("Images"), 0, 0)
        self._img_folder_entry = _entry("Select folder…")
        src_gl.addWidget(self._img_folder_entry, 0, 1)
        browse_img = _sec_btn("Browse")
        browse_img.setFixedWidth(84)
        browse_img.clicked.connect(self._browse_images)
        src_gl.addWidget(browse_img, 0, 2)

        self._img_count_lbl = QLabel("")
        self._img_count_lbl.setFont(QFont(theme.FONT_FAMILY, theme.FONT_SIZE_SM))
        self._img_count_lbl.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        src_gl.addWidget(self._img_count_lbl, 1, 1, 1, 2)

        src_gl.addWidget(_lbl("Audio"), 2, 0)
        self._audio_entry = _entry("Select MP3, WAV, or M4A…")
        src_gl.addWidget(self._audio_entry, 2, 1)
        browse_aud = _sec_btn("Browse")
        browse_aud.setFixedWidth(84)
        browse_aud.clicked.connect(self._browse_audio)
        src_gl.addWidget(browse_aud, 2, 2)

        form.addWidget(src_outer)

        # ── Timing ─────────────────────────────────────────────────────────
        tim_outer, tim = _card(container, "TIMING")
        tim_vl = QVBoxLayout(tim)
        tim_vl.setContentsMargins(16, 10, 16, 12)
        tim_vl.setSpacing(6)

        self._timing_group = QButtonGroup(self)

        # ── Smart — Deepgram ───────────────────────────────────────────────
        self._rb_smart = _radio(
            "Smart — Deepgram  (uses timestamps embedded in prompts if present, else transcribes + aligns)",
            self._timing_group,
        )
        self._rb_smart.setChecked(True)
        tim_vl.addWidget(self._rb_smart)

        self._key_bg = QFrame()
        self._key_bg.setStyleSheet(f"""
            QFrame {{
                background: {theme.BG_ELEVATED};
                border: 1px solid {theme.BORDER};
                border-radius: {theme.RADIUS_SM}px;
            }}
            QLabel {{ background: transparent; border: none; }}
        """)
        key_hl = QHBoxLayout(self._key_bg)
        key_hl.setContentsMargins(12, 6, 12, 6)
        key_hl.setSpacing(8)
        key_hl.addWidget(_lbl("API Key", 64, theme.FONT_SIZE_SM, theme.TEXT_MUTED))
        self._dg_key_entry = QLineEdit()
        self._dg_key_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self._dg_key_entry.setPlaceholderText("Paste Deepgram key (free at console.deepgram.com)")
        self._dg_key_entry.setFont(QFont(theme.FONT_FAMILY, theme.FONT_SIZE_BASE))
        self._dg_key_entry.setStyleSheet(
            "background: transparent; border: none; color: " + theme.INPUT_TEXT + ";"
        )
        self._dg_key_entry.setText(self.app.config.get("deepgram_key", ""))
        key_hl.addWidget(self._dg_key_entry, stretch=1)
        tim_vl.addWidget(self._key_bg)

        # ── Smart — Manual transcript ──────────────────────────────────────
        self._rb_smart_manual = _radio(
            "Smart — Manual transcript  (uses timestamps embedded in prompts if present, else paste transcript)",
            self._timing_group,
        )
        tim_vl.addWidget(self._rb_smart_manual)

        self._transcript_area = QTextEdit()
        self._transcript_area.setPlaceholderText(
            "Paste the full transcript here.\n\n"
            "Timing is estimated proportionally — the app then uses sentence embeddings\n"
            "to align each image prompt to the passage of speech that describes it."
        )
        self._transcript_area.setFont(QFont("Consolas", theme.FONT_SIZE_SM))
        self._transcript_area.setFixedHeight(120)
        self._transcript_area.setVisible(False)
        self._transcript_area.setStyleSheet(f"""
            QTextEdit {{
                background: {theme.BG_ELEVATED};
                border: 1px solid {theme.BORDER};
                border-radius: {theme.RADIUS_SM}px;
                padding: 8px;
                color: {theme.INPUT_TEXT};
            }}
        """)
        tim_vl.addWidget(self._transcript_area)

        # Show/hide sub-widgets based on which Smart mode is active
        self._rb_smart.toggled.connect(self._key_bg.setVisible)
        self._rb_smart_manual.toggled.connect(self._transcript_area.setVisible)

        # ── LLM Alignment panel (visible whenever any Smart mode is active) ──
        self._llm_panel = QFrame()
        self._llm_panel.setStyleSheet(f"""
            QFrame {{
                background: {theme.BG_ELEVATED};
                border: 1px solid {theme.BORDER};
                border-radius: {theme.RADIUS_SM}px;
            }}
            QLabel {{ background: transparent; border: none; }}
            QRadioButton {{ background: transparent; }}
        """)
        lp_vl = QVBoxLayout(self._llm_panel)
        lp_vl.setContentsMargins(12, 8, 12, 10)
        lp_vl.setSpacing(6)

        lp_title = QLabel("ALIGNMENT API")
        lp_title.setFont(QFont(theme.FONT_FAMILY, theme.FONT_SIZE_XS, QFont.Weight.Bold))
        lp_title.setStyleSheet(f"color: {theme.SECTION_LABEL_TEXT};")
        lp_vl.addWidget(lp_title)

        # Provider row
        prov_row = QWidget()
        prov_row.setStyleSheet("background: transparent;")
        prov_hl = QHBoxLayout(prov_row)
        prov_hl.setContentsMargins(0, 0, 0, 0)
        prov_hl.setSpacing(16)

        self._llm_group = QButtonGroup(self)
        self._rb_groq = _radio("Groq  (free, fast)", self._llm_group)
        self._rb_groq.setChecked(True)
        prov_hl.addWidget(self._rb_groq)

        self._rb_openrouter = _radio("OpenRouter", self._llm_group)
        prov_hl.addWidget(self._rb_openrouter)

        self._rb_openai = _radio("ChatGPT (OpenAI)", self._llm_group)
        prov_hl.addWidget(self._rb_openai)
        prov_hl.addStretch()
        lp_vl.addWidget(prov_row)

        # API key row
        key_row = QWidget()
        key_row.setStyleSheet("background: transparent;")
        key_hl2 = QHBoxLayout(key_row)
        key_hl2.setContentsMargins(0, 0, 0, 0)
        key_hl2.setSpacing(8)
        key_hl2.addWidget(_lbl("API Key", 64, theme.FONT_SIZE_SM, theme.TEXT_MUTED))
        self._llm_key_entry = QLineEdit()
        self._llm_key_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self._llm_key_entry.setPlaceholderText("Groq: gsk_…  /  OpenRouter: sk-or-…  /  OpenAI: sk-…")
        self._llm_key_entry.setFont(QFont(theme.FONT_FAMILY, theme.FONT_SIZE_BASE))
        self._llm_key_entry.setStyleSheet(f"""
            background: {theme.INPUT_BG}; border: 1px solid {theme.INPUT_BORDER};
            border-radius: {theme.RADIUS_SM}px; padding: 5px 8px; color: {theme.INPUT_TEXT};
        """)
        self._llm_key_entry.setText(self.app.config.get("llm_key", ""))
        key_hl2.addWidget(self._llm_key_entry, stretch=1)
        lp_vl.addWidget(key_row)

        # Model override row (optional — defaults are sensible per-provider)
        model_row = QWidget()
        model_row.setStyleSheet("background: transparent;")
        model_hl = QHBoxLayout(model_row)
        model_hl.setContentsMargins(0, 0, 0, 0)
        model_hl.setSpacing(8)
        model_hl.addWidget(_lbl("Model", 64, theme.FONT_SIZE_SM, theme.TEXT_MUTED))
        self._llm_model_entry = QLineEdit()
        self._llm_model_entry.setPlaceholderText(GROQ_MODEL)
        self._llm_model_entry.setFont(QFont(theme.FONT_FAMILY, theme.FONT_SIZE_BASE))
        self._llm_model_entry.setStyleSheet(f"""
            background: {theme.INPUT_BG}; border: 1px solid {theme.INPUT_BORDER};
            border-radius: {theme.RADIUS_SM}px; padding: 5px 8px; color: {theme.INPUT_TEXT};
        """)
        model_hl.addWidget(self._llm_model_entry, stretch=1)
        lp_vl.addWidget(model_row)

        def _update_model_placeholder():
            if self._rb_groq.isChecked():
                self._llm_model_entry.setPlaceholderText(GROQ_MODEL)
            elif self._rb_openrouter.isChecked():
                self._llm_model_entry.setPlaceholderText(OPENROUTER_MODEL)
            else:
                self._llm_model_entry.setPlaceholderText(OPENAI_MODEL)
        self._rb_groq.toggled.connect(lambda _: _update_model_placeholder())
        self._rb_openrouter.toggled.connect(lambda _: _update_model_placeholder())
        self._rb_openai.toggled.connect(lambda _: _update_model_placeholder())

        tim_vl.addWidget(self._llm_panel)

        # Show LLM panel when either Smart radio is checked
        def _update_llm_panel():
            self._llm_panel.setVisible(
                self._rb_smart.isChecked() or self._rb_smart_manual.isChecked()
            )
        self._rb_smart.toggled.connect(lambda _: _update_llm_panel())
        self._rb_smart_manual.toggled.connect(lambda _: _update_llm_panel())

        # ── Equal ──────────────────────────────────────────────────────────
        self._rb_equal = _radio(
            "Equal  —  split audio evenly across images", self._timing_group
        )
        tim_vl.addWidget(self._rb_equal)

        # ── Fixed ──────────────────────────────────────────────────────────
        fix_row = QWidget()
        fix_row.setStyleSheet("background: transparent;")
        fix_hl = QHBoxLayout(fix_row)
        fix_hl.setContentsMargins(0, 0, 0, 0)
        fix_hl.setSpacing(6)
        self._rb_fixed = _radio("Fixed  —", self._timing_group)
        fix_hl.addWidget(self._rb_fixed)
        self._fixed_sec_entry = QLineEdit("4.0")
        self._fixed_sec_entry.setFixedWidth(56)
        self._fixed_sec_entry.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._fixed_sec_entry.setStyleSheet(f"""
            background: {theme.INPUT_BG}; border: 1px solid {theme.INPUT_BORDER};
            border-radius: {theme.RADIUS_SM}px; padding: 4px; color: {theme.INPUT_TEXT};
        """)
        fix_hl.addWidget(self._fixed_sec_entry)
        fix_hl.addWidget(_lbl("sec/image (scaled to audio length)", 0, theme.FONT_SIZE_SM, theme.TEXT_MUTED))
        fix_hl.addStretch()
        tim_vl.addWidget(fix_row)

        form.addWidget(tim_outer)

        # ── Format & Transitions ────────────────────────────────────────────
        fmt_outer, fmt = _card(container, "FORMAT & TRANSITIONS")
        fmt_vl = QVBoxLayout(fmt)
        fmt_vl.setContentsMargins(16, 10, 16, 12)
        fmt_vl.setSpacing(8)

        # Aspect ratio
        ratio_row = QWidget()
        ratio_row.setStyleSheet("background: transparent;")
        ratio_hl = QHBoxLayout(ratio_row)
        ratio_hl.setContentsMargins(0, 0, 0, 0)
        ratio_hl.setSpacing(24)
        ratio_hl.addWidget(_lbl("Ratio", 60))

        self._ratio_group = QButtonGroup(self)
        rb_169 = _radio("16:9  YouTube / Landscape", self._ratio_group)
        rb_169.setChecked(True)
        self._rb_169 = rb_169
        ratio_hl.addWidget(rb_169)
        rb_916 = _radio("9:16  TikTok / Shorts", self._ratio_group)
        self._rb_916 = rb_916
        ratio_hl.addWidget(rb_916)
        ratio_hl.addStretch()
        fmt_vl.addWidget(ratio_row)

        # Transition mode
        trans_sep = QFrame()
        trans_sep.setFixedHeight(1)
        trans_sep.setStyleSheet(f"background: {theme.BORDER_SUBTLE};")
        fmt_vl.addWidget(trans_sep)

        self._trans_group = QButtonGroup(self)

        # Fixed
        fix_tr = QWidget()
        fix_tr.setStyleSheet("background: transparent;")
        fix_tr_hl = QHBoxLayout(fix_tr)
        fix_tr_hl.setContentsMargins(0, 4, 0, 4)
        fix_tr_hl.setSpacing(10)
        self._rb_trans_fixed = _radio("Fixed", self._trans_group)
        self._rb_trans_fixed.setChecked(True)
        fix_tr_hl.addWidget(self._rb_trans_fixed)
        self._fixed_trans_combo = QComboBox()
        self._fixed_trans_combo.addItems(TRANSITIONS)
        self._fixed_trans_combo.setFixedWidth(180)
        self._fixed_trans_combo.setStyleSheet(f"""
            QComboBox {{ background: {theme.INPUT_BG}; color: {theme.TEXT_PRIMARY};
                border: 1px solid {theme.INPUT_BORDER}; border-radius: {theme.RADIUS_SM}px;
                padding: 5px 10px; font-size: 13px; }}
            QComboBox:focus {{ border-color: {theme.INPUT_BORDER_FOCUS}; }}
            QComboBox QAbstractItemView {{
                background: {theme.BG_SURFACE}; color: {theme.TEXT_PRIMARY};
                border: 1px solid {theme.BORDER}; selection-background-color: {theme.ACCENT_LIGHT};
                selection-color: {theme.TEXT_PRIMARY};
            }}
        """)
        fix_tr_hl.addWidget(self._fixed_trans_combo)
        fix_tr_hl.addStretch()
        fmt_vl.addWidget(fix_tr)

        # Random
        rand_tr = QWidget()
        rand_tr.setStyleSheet("background: transparent;")
        rand_vl = QVBoxLayout(rand_tr)
        rand_vl.setContentsMargins(0, 0, 0, 0)
        rand_vl.setSpacing(4)
        rand_top = QWidget()
        rand_top.setStyleSheet("background: transparent;")
        rand_top_hl = QHBoxLayout(rand_top)
        rand_top_hl.setContentsMargins(0, 4, 0, 0)
        self._rb_trans_random = _radio("Random", self._trans_group)
        rand_top_hl.addWidget(self._rb_trans_random)
        rand_top_hl.addStretch()
        rand_vl.addWidget(rand_top)

        chk_container = QWidget()
        chk_container.setStyleSheet("background: transparent;")
        chk_gl = QGridLayout(chk_container)
        chk_gl.setContentsMargins(28, 0, 0, 4)
        chk_gl.setSpacing(4)
        popular = ["fade", "dissolve", "fadeblack", "wipeleft", "wiperight",
                   "slideleft", "slideright", "zoomin", "radial"]
        self._rand_checks: dict[str, QCheckBox] = {}
        for i, t in enumerate(popular):
            cb = QCheckBox(t)
            cb.setChecked(t in ("fade", "dissolve"))
            cb.setFont(QFont(theme.FONT_FAMILY, theme.FONT_SIZE_SM))
            cb.setStyleSheet(f"""
                QCheckBox {{ color: {theme.TEXT_PRIMARY}; spacing: 5px; }}
                QCheckBox::indicator {{
                    width: 14px; height: 14px; border-radius: 4px;
                    border: 2px solid {theme.BORDER_STRONG}; background: {theme.WHITE};
                }}
                QCheckBox::indicator:checked {{
                    background: {theme.ACCENT}; border-color: {theme.ACCENT};
                }}
            """)
            chk_gl.addWidget(cb, i // 3, i % 3)
            self._rand_checks[t] = cb
        rand_vl.addWidget(chk_container)
        fmt_vl.addWidget(rand_tr)

        # Manual
        man_tr = QWidget()
        man_tr.setStyleSheet("background: transparent;")
        man_hl = QHBoxLayout(man_tr)
        man_hl.setContentsMargins(0, 4, 0, 4)
        man_hl.setSpacing(10)
        self._rb_trans_manual = _radio("Manual", self._trans_group)
        man_hl.addWidget(self._rb_trans_manual)
        edit_cuts_btn = _sec_btn("Edit cuts →")
        edit_cuts_btn.setFixedWidth(110)
        edit_cuts_btn.clicked.connect(self._open_manual_cuts)
        man_hl.addWidget(edit_cuts_btn)
        man_hl.addStretch()
        fmt_vl.addWidget(man_tr)

        # Duration
        dur_row = QWidget()
        dur_row.setStyleSheet("background: transparent;")
        dur_hl = QHBoxLayout(dur_row)
        dur_hl.setContentsMargins(0, 0, 0, 0)
        dur_hl.setSpacing(8)
        dur_hl.addWidget(_lbl("Duration", 80))
        self._trans_dur_entry = QLineEdit("0.5")
        self._trans_dur_entry.setFixedWidth(56)
        self._trans_dur_entry.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._trans_dur_entry.setStyleSheet(f"""
            background: {theme.INPUT_BG}; border: 1px solid {theme.INPUT_BORDER};
            border-radius: {theme.RADIUS_SM}px; padding: 4px; color: {theme.INPUT_TEXT};
        """)
        dur_hl.addWidget(self._trans_dur_entry)
        dur_hl.addWidget(_lbl("seconds", 0, theme.FONT_SIZE_SM, theme.TEXT_MUTED))
        dur_hl.addStretch()
        fmt_vl.addWidget(dur_row)

        form.addWidget(fmt_outer)

        # ── Ken Burns Effect ────────────────────────────────────────────────
        kb_outer, kb = _card(container, "KEN BURNS EFFECT")
        kb_vl = QVBoxLayout(kb)
        kb_vl.setContentsMargins(16, 10, 16, 12)
        kb_vl.setSpacing(6)

        self._zoom_group = QButtonGroup(self)
        zoom_options = [
            ("none",     "None  —  images are static"),
            ("zoom_in",  "Zoom In  —  slowly push into each image"),
            ("zoom_out", "Zoom Out  —  pull back from each image"),
            ("random",   "Random  —  zoom in or out per image"),
        ]
        self._zoom_rbs: dict[str, QRadioButton] = {}
        for val, label in zoom_options:
            rb = _radio(label, self._zoom_group)
            if val == "none":
                rb.setChecked(True)
            kb_vl.addWidget(rb)
            self._zoom_rbs[val] = rb

        # Intensity
        int_row = QWidget()
        int_row.setStyleSheet("background: transparent;")
        int_hl = QHBoxLayout(int_row)
        int_hl.setContentsMargins(0, 4, 0, 0)
        int_hl.setSpacing(8)
        int_hl.addWidget(_lbl("Intensity", 80))

        int_hl.addWidget(_lbl("5%", 0, theme.FONT_SIZE_SM, theme.TEXT_MUTED))

        self._zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._zoom_slider.setMinimum(5)
        self._zoom_slider.setMaximum(50)
        self._zoom_slider.setValue(20)
        self._zoom_slider.setFixedWidth(260)
        self._zoom_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                background: {theme.PROGRESS_TRACK}; height: 4px; border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: {theme.GREY_900}; width: 16px; height: 16px;
                border-radius: 8px; margin: -6px 0;
            }}
            QSlider::handle:horizontal:hover {{ background: {theme.ACCENT}; }}
            QSlider::sub-page:horizontal {{
                background: {theme.ACCENT}; border-radius: 2px;
            }}
        """)
        self._zoom_slider.valueChanged.connect(self._on_zoom_slider)
        int_hl.addWidget(self._zoom_slider)

        int_hl.addWidget(_lbl("50%", 0, theme.FONT_SIZE_SM, theme.TEXT_MUTED))

        self._zoom_pct_lbl = QLabel("20%")
        self._zoom_pct_lbl.setFont(QFont(theme.FONT_FAMILY, theme.FONT_SIZE_BASE))
        self._zoom_pct_lbl.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; min-width: 40px;")
        int_hl.addWidget(self._zoom_pct_lbl)
        int_hl.addStretch()
        kb_vl.addWidget(int_row)

        form.addWidget(kb_outer)

        # ── Captions ─────────────────────────────────────────────────────────
        cap_outer, cap = _card(container, "CAPTIONS")
        cap_vl = QVBoxLayout(cap)
        cap_vl.setContentsMargins(16, 10, 16, 12)
        cap_vl.setSpacing(8)

        self._cap_enable = QCheckBox("Burn karaoke-style word-highlight captions into the video")
        self._cap_enable.setFont(QFont(theme.FONT_FAMILY, theme.FONT_SIZE_BASE))
        self._cap_enable.setStyleSheet(f"""
            QCheckBox {{ color: {theme.TEXT_PRIMARY}; spacing: 8px; background: transparent; }}
            QCheckBox::indicator {{
                width: 16px; height: 16px; border-radius: 4px;
                border: 2px solid {theme.BORDER_STRONG}; background: {theme.WHITE};
            }}
            QCheckBox::indicator:checked {{ background: {theme.ACCENT}; border-color: {theme.ACCENT}; }}
        """)
        cap_vl.addWidget(self._cap_enable)

        self._cap_controls = QFrame()
        self._cap_controls.setStyleSheet("QFrame { background: transparent; }")
        cc_vl = QVBoxLayout(self._cap_controls)
        cc_vl.setContentsMargins(0, 8, 0, 0)
        cc_vl.setSpacing(8)

        # Font + size row
        font_row = QWidget()
        font_row.setStyleSheet("background: transparent;")
        font_hl = QHBoxLayout(font_row)
        font_hl.setContentsMargins(0, 0, 0, 0)
        font_hl.setSpacing(8)
        font_hl.addWidget(_lbl("Font", 60))
        self._cap_font_combo = QComboBox()
        self._cap_font_combo.addItems(sorted(QFontDatabase.families()))
        default_idx = self._cap_font_combo.findText("Segoe UI")
        if default_idx >= 0:
            self._cap_font_combo.setCurrentIndex(default_idx)
        self._cap_font_combo.setStyleSheet(f"""
            QComboBox {{ background: {theme.INPUT_BG}; color: {theme.TEXT_PRIMARY};
                border: 1px solid {theme.INPUT_BORDER}; border-radius: {theme.RADIUS_SM}px;
                padding: 5px 8px; }}
            QComboBox QAbstractItemView {{
                background: {theme.BG_SURFACE}; color: {theme.TEXT_PRIMARY};
                border: 1px solid {theme.BORDER}; selection-background-color: {theme.ACCENT_LIGHT};
                selection-color: {theme.TEXT_PRIMARY};
            }}
        """)
        font_hl.addWidget(self._cap_font_combo, stretch=1)

        font_hl.addWidget(_lbl("Size", 40))
        self._cap_size_spin = QSpinBox()
        self._cap_size_spin.setRange(12, 160)
        self._cap_size_spin.setValue(56)
        self._cap_size_spin.setFixedWidth(70)
        self._cap_size_spin.setStyleSheet(f"""
            QSpinBox {{ background: {theme.INPUT_BG}; color: {theme.TEXT_PRIMARY};
                border: 1px solid {theme.INPUT_BORDER}; border-radius: {theme.RADIUS_SM}px; padding: 4px; }}
        """)
        font_hl.addWidget(self._cap_size_spin)
        cc_vl.addWidget(font_row)

        # Bold + position row
        style_row = QWidget()
        style_row.setStyleSheet("background: transparent;")
        style_hl = QHBoxLayout(style_row)
        style_hl.setContentsMargins(0, 0, 0, 0)
        style_hl.setSpacing(8)
        self._cap_bold_chk = QCheckBox("Bold")
        self._cap_bold_chk.setChecked(True)
        self._cap_bold_chk.setFont(QFont(theme.FONT_FAMILY, theme.FONT_SIZE_BASE))
        self._cap_bold_chk.setStyleSheet(f"""
            QCheckBox {{ color: {theme.TEXT_PRIMARY}; spacing: 6px; background: transparent; }}
            QCheckBox::indicator {{
                width: 14px; height: 14px; border-radius: 4px;
                border: 2px solid {theme.BORDER_STRONG}; background: {theme.WHITE};
            }}
            QCheckBox::indicator:checked {{ background: {theme.ACCENT}; border-color: {theme.ACCENT}; }}
        """)
        style_hl.addWidget(self._cap_bold_chk)

        style_hl.addWidget(_lbl("Position", 60))
        self._cap_position_combo = QComboBox()
        self._cap_position_combo.addItems(["bottom", "middle", "top"])
        self._cap_position_combo.setFixedWidth(100)
        self._cap_position_combo.setStyleSheet(self._cap_font_combo.styleSheet())
        style_hl.addWidget(self._cap_position_combo)
        style_hl.addStretch()
        cc_vl.addWidget(style_row)

        # Color swatches row
        color_row = QWidget()
        color_row.setStyleSheet("background: transparent;")
        color_hl = QHBoxLayout(color_row)
        color_hl.setContentsMargins(0, 0, 0, 0)
        color_hl.setSpacing(10)

        self._cap_text_qcolor = QColor(255, 255, 255)
        self._cap_highlight_qcolor = QColor(255, 214, 0)
        self._cap_outline_qcolor = QColor(0, 0, 0)

        def _make_swatch(label_text, initial: QColor, on_pick):
            wrap = QWidget()
            wrap.setStyleSheet("background: transparent;")
            hl = QHBoxLayout(wrap)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(6)
            hl.addWidget(_lbl(label_text, 70, theme.FONT_SIZE_SM, theme.TEXT_MUTED))
            btn = QPushButton()
            btn.setFixedSize(32, 24)
            btn.setStyleSheet(
                f"background: {initial.name()}; border: 1px solid {theme.BORDER_STRONG}; "
                f"border-radius: {theme.RADIUS_SM}px;"
            )
            btn.clicked.connect(lambda: on_pick(btn))
            hl.addWidget(btn)
            return wrap, btn

        def _pick_text_color(btn):
            c = QColorDialog.getColor(self._cap_text_qcolor, self, "Text color")
            if c.isValid():
                self._cap_text_qcolor = c
                btn.setStyleSheet(
                    f"background: {c.name()}; border: 1px solid {theme.BORDER_STRONG}; "
                    f"border-radius: {theme.RADIUS_SM}px;"
                )
                self._schedule_caption_preview()

        def _pick_highlight_color(btn):
            c = QColorDialog.getColor(self._cap_highlight_qcolor, self, "Highlight color")
            if c.isValid():
                self._cap_highlight_qcolor = c
                btn.setStyleSheet(
                    f"background: {c.name()}; border: 1px solid {theme.BORDER_STRONG}; "
                    f"border-radius: {theme.RADIUS_SM}px;"
                )
                self._schedule_caption_preview()

        def _pick_outline_color(btn):
            c = QColorDialog.getColor(self._cap_outline_qcolor, self, "Outline color")
            if c.isValid():
                self._cap_outline_qcolor = c
                btn.setStyleSheet(
                    f"background: {c.name()}; border: 1px solid {theme.BORDER_STRONG}; "
                    f"border-radius: {theme.RADIUS_SM}px;"
                )
                self._schedule_caption_preview()

        text_swatch, _ = _make_swatch("Text", self._cap_text_qcolor, _pick_text_color)
        highlight_swatch, _ = _make_swatch("Highlight", self._cap_highlight_qcolor, _pick_highlight_color)
        outline_swatch, _ = _make_swatch("Outline", self._cap_outline_qcolor, _pick_outline_color)
        color_hl.addWidget(text_swatch)
        color_hl.addWidget(highlight_swatch)
        color_hl.addWidget(outline_swatch)

        color_hl.addWidget(_lbl("Outline width", 90, theme.FONT_SIZE_SM, theme.TEXT_MUTED))
        self._cap_outline_spin = QSpinBox()
        self._cap_outline_spin.setRange(0, 12)
        self._cap_outline_spin.setValue(3)
        self._cap_outline_spin.setFixedWidth(55)
        self._cap_outline_spin.setStyleSheet(self._cap_size_spin.styleSheet())
        color_hl.addWidget(self._cap_outline_spin)
        color_hl.addStretch()
        cc_vl.addWidget(color_row)

        # Live preview
        preview_wrap = QWidget()
        preview_wrap.setStyleSheet("background: transparent;")
        pv_vl = QVBoxLayout(preview_wrap)
        pv_vl.setContentsMargins(0, 4, 0, 0)
        pv_vl.setSpacing(4)
        pv_vl.addWidget(_lbl("PREVIEW", 0, theme.FONT_SIZE_XS, theme.TEXT_MUTED))

        self._cap_preview = QLabel()
        self._cap_preview.setFixedSize(320, 180)
        self._cap_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cap_preview.setStyleSheet(f"""
            background: {theme.GREY_900};
            border: 1px solid {theme.BORDER};
            border-radius: {theme.RADIUS_SM}px;
        """)
        self._cap_preview.setScaledContents(False)
        pv_vl.addWidget(self._cap_preview)
        cc_vl.addWidget(preview_wrap)

        cap_vl.addWidget(self._cap_controls)
        form.addWidget(cap_outer)

        # Wire up live preview updates
        self._cap_enable.toggled.connect(self._cap_controls.setVisible)
        self._cap_enable.toggled.connect(lambda _: self._schedule_caption_preview())
        self._cap_font_combo.currentTextChanged.connect(lambda _: self._schedule_caption_preview())
        self._cap_size_spin.valueChanged.connect(lambda _: self._schedule_caption_preview())
        self._cap_bold_chk.toggled.connect(lambda _: self._schedule_caption_preview())
        self._cap_position_combo.currentTextChanged.connect(lambda _: self._schedule_caption_preview())
        self._cap_outline_spin.valueChanged.connect(lambda _: self._schedule_caption_preview())
        self._cap_controls.setVisible(False)
        self._rb_169.toggled.connect(lambda _: self._schedule_caption_preview())
        self._rb_916.toggled.connect(lambda _: self._schedule_caption_preview())

        # ── Output ──────────────────────────────────────────────────────────
        out_outer, out = _card(container, "OUTPUT")
        out_gl = QGridLayout(out)
        out_gl.setContentsMargins(16, 10, 16, 12)
        out_gl.setSpacing(8)
        out_gl.setColumnStretch(1, 1)

        out_gl.addWidget(_lbl("Save as"), 0, 0)
        self._output_entry = _entry("output.mp4")
        out_gl.addWidget(self._output_entry, 0, 1)
        browse_out = _sec_btn("Browse")
        browse_out.setFixedWidth(84)
        browse_out.clicked.connect(self._browse_output)
        out_gl.addWidget(browse_out, 0, 2)

        form.addWidget(out_outer)
        form.addStretch()

        # ── Action bar ─────────────────────────────────────────────────────
        action = QFrame()
        action.setStyleSheet(f"""
            QFrame {{
                background: {theme.CARD_BG};
                border: 1px solid {theme.CARD_BORDER};
                border-top-left-radius: 0; border-top-right-radius: 0;
                border-radius: {theme.RADIUS_MD}px;
            }}
            QLabel {{ background: transparent; border: none; }}
        """)
        action_vl = QVBoxLayout(action)
        action_vl.setContentsMargins(16, 12, 16, 12)
        action_vl.setSpacing(6)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedHeight(6)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background: {theme.PROGRESS_TRACK}; border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background: {theme.PROGRESS_FILL}; border-radius: 3px;
            }}
        """)
        action_vl.addWidget(self._progress_bar)

        bottom_row = QWidget()
        bottom_row.setStyleSheet("background: transparent;")
        bottom_hl = QHBoxLayout(bottom_row)
        bottom_hl.setContentsMargins(0, 0, 0, 0)
        bottom_hl.setSpacing(12)

        self._video_status_lbl = QLabel("")
        self._video_status_lbl.setFont(QFont(theme.FONT_FAMILY, theme.FONT_SIZE_SM))
        self._video_status_lbl.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        bottom_hl.addWidget(self._video_status_lbl, stretch=1)

        self._create_btn = QPushButton("▶   Create Video")
        self._create_btn.setFixedSize(172, 40)
        self._create_btn.setStyleSheet(f"""
            QPushButton {{
                background: {theme.BTN_PRIMARY_BG}; color: {theme.BTN_PRIMARY_TEXT};
                border: none; border-radius: {theme.RADIUS_SM}px;
                font-weight: bold; font-size: 14px;
            }}
            QPushButton:hover {{ background: {theme.BTN_PRIMARY_HOVER}; }}
            QPushButton:disabled {{
                background: {theme.BTN_DISABLED_BG}; color: {theme.BTN_DISABLED_TEXT};
            }}
        """)
        self._create_btn.clicked.connect(self._create_video)
        bottom_hl.addWidget(self._create_btn)

        action_vl.addWidget(bottom_row)

        # Full scrolling FFmpeg log — the status line above only shows the
        # latest message, so on failure there was nothing left to inspect.
        self._log_view = QTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setFont(QFont("Consolas", theme.FONT_SIZE_SM))
        self._log_view.setFixedHeight(140)
        self._log_view.setVisible(False)
        self._log_view.setStyleSheet(f"""
            QTextEdit {{
                background: {theme.GREY_900}; color: {theme.GREY_100};
                border: 1px solid {theme.BORDER}; border-radius: {theme.RADIUS_SM}px;
                padding: 8px;
            }}
        """)
        action_vl.addWidget(self._log_view)

        outer_vl.addWidget(action)

        self._schedule_caption_preview()

    # ── Captions preview ─────────────────────────────────────────────────────
    def _schedule_caption_preview(self):
        """Debounce rapid control changes (typing, slider drag) into a
        single preview render ~180ms after things go quiet."""
        if not hasattr(self, "_cap_preview"):
            return
        if not hasattr(self, "_cap_preview_timer"):
            self._cap_preview_timer = QTimer(self)
            self._cap_preview_timer.setSingleShot(True)
            self._cap_preview_timer.timeout.connect(self._render_caption_preview_now)
        self._cap_preview_timer.start(180)

    def _render_caption_preview_now(self):
        is_916 = self._rb_916.isChecked()
        box_w, box_h = (180, 320) if is_916 else (320, 180)
        if self._cap_preview.width() != box_w or self._cap_preview.height() != box_h:
            self._cap_preview.setFixedSize(box_w, box_h)

        if not self._cap_enable.isChecked():
            # No captions to preview — just show the background, no ffmpeg needed.
            pix = QPixmap(box_w, box_h)
            pix.fill(QColor(20, 20, 20))
            if self._image_paths:
                try:
                    src = QPixmap(str(self._image_paths[0]))
                    if not src.isNull():
                        scaled = src.scaled(
                            box_w, box_h,
                            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                        painter = QPainter(pix)
                        x = (scaled.width() - box_w) // 2
                        y = (scaled.height() - box_h) // 2
                        painter.drawPixmap(-x, -y, scaled)
                        painter.end()
                except Exception:
                    pass
            self._cap_preview.setPixmap(pix)
            return

        if getattr(self, "_cap_preview_busy", False):
            self._cap_preview_pending = True
            return
        self._cap_preview_busy = True

        video_w, video_h = (1080, 1920) if is_916 else (1920, 1080)
        bg = self._image_paths[0] if self._image_paths else None
        kwargs = dict(
            output_png=Path(tempfile.gettempdir()) / "vse_caption_preview.png",
            video_w=video_w, video_h=video_h, background_image=bg,
            font_family=self._cap_font_combo.currentText() or "Segoe UI",
            font_size=self._cap_size_spin.value(),
            text_color=(self._cap_text_qcolor.red(), self._cap_text_qcolor.green(), self._cap_text_qcolor.blue()),
            highlight_color=(
                self._cap_highlight_qcolor.red(), self._cap_highlight_qcolor.green(), self._cap_highlight_qcolor.blue()
            ),
            outline_color=(
                self._cap_outline_qcolor.red(), self._cap_outline_qcolor.green(), self._cap_outline_qcolor.blue()
            ),
            outline_width=float(self._cap_outline_spin.value()),
            position=self._cap_position_combo.currentText(),
            margin_v=80,
            bold=self._cap_bold_chk.isChecked(),
        )
        worker = _CaptionPreviewWorker(**kwargs)
        worker.done.connect(self._on_caption_preview_done)
        worker.failed.connect(self._on_caption_preview_failed)
        self._cap_preview_worker = worker
        worker.start()

    def _on_caption_preview_done(self, path: str):
        self._cap_preview_busy = False
        pix = QPixmap(path)
        if not pix.isNull():
            box_w, box_h = self._cap_preview.width(), self._cap_preview.height()
            scaled = pix.scaled(
                box_w, box_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._cap_preview.setPixmap(scaled)
        if getattr(self, "_cap_preview_pending", False):
            self._cap_preview_pending = False
            self._render_caption_preview_now()

    def _on_caption_preview_failed(self, msg: str):
        self._cap_preview_busy = False
        if getattr(self, "_cap_preview_pending", False):
            self._cap_preview_pending = False
            self._render_caption_preview_now()

    # ── Slider ─────────────────────────────────────────────────────────────
    def _on_zoom_slider(self, value: int):
        self._zoom_pct_lbl.setText(f"{value}%")

    # ── Source helpers ──────────────────────────────────────────────────────
    def set_image_pairs(self, pairs: list):
        self._image_paths = [Path(p) for p, _ in pairs]
        if self._image_paths:
            self._img_folder_entry.setText(str(self._image_paths[0].parent))
            n = len(self._image_paths)
            self._img_count_lbl.setText(
                f"  {n} image{'s' if n != 1 else ''} loaded from Import"
            )
            self._img_count_lbl.setStyleSheet(f"color: {theme.SUCCESS};")
            self._manual_cuts = ["fade"] * max(0, n - 1)
        self._schedule_caption_preview()

    def _browse_images(self):
        folder = QFileDialog.getExistingDirectory(self, "Select images folder")
        if folder:
            self._img_folder_entry.setText(folder)
            self._refresh_image_count(folder)

    def _refresh_image_count(self, folder: str):
        p = Path(folder)
        if p.is_dir():
            exts = {".jpg", ".jpeg", ".png", ".webp"}
            imgs = sorted((f for f in p.iterdir() if f.suffix.lower() in exts), key=_natural_key)
            self._image_paths = imgs
            self._img_count_lbl.setText(
                f"  {len(imgs)} image{'s' if len(imgs) != 1 else ''} found"
            )
            self._img_count_lbl.setStyleSheet(
                f"color: {theme.SUCCESS if imgs else theme.WARNING};"
            )
            self._manual_cuts = ["fade"] * max(0, len(imgs) - 1)
        else:
            self._image_paths = []
            self._img_count_lbl.setText("")
        self._schedule_caption_preview()

    def _browse_audio(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select audio file", "",
            "Audio (*.mp3 *.wav *.m4a *.aac *.ogg);;All files (*.*)"
        )
        if path:
            self._audio_entry.setText(path)

    def _browse_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save video as", "output.mp4", "MP4 video (*.mp4)"
        )
        if path:
            self._output_entry.setText(path)

    # ── Manual cuts dialog ──────────────────────────────────────────────────
    def _open_manual_cuts(self):
        if not self._image_paths:
            self.app.set_status("⚠  Load images first")
            return
        n = len(self._image_paths)
        if n < 2:
            self.app.set_status("⚠  Need at least 2 images for transitions")
            return

        from PySide6.QtWidgets import QDialog, QScrollArea, QDialogButtonBox

        dlg = QDialog(self)
        dlg.setWindowTitle("Manual Transitions")
        dlg.resize(460, 520)
        dlg.setStyleSheet(f"background: {theme.BG_APP};")

        dv = QVBoxLayout(dlg)
        dv.setContentsMargins(16, 16, 16, 16)
        dv.setSpacing(12)

        t = QLabel("Transition per cut")
        t.setFont(QFont(theme.FONT_FAMILY, 15, QFont.Weight.Bold))
        t.setStyleSheet(f"color: {theme.TEXT_PRIMARY};")
        dv.addWidget(t)

        sub = QLabel(f"{n-1} cut{'s' if n-1!=1 else ''} between {n} images")
        sub.setFont(QFont(theme.FONT_FAMILY, theme.FONT_SIZE_BASE))
        sub.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        dv.addWidget(sub)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"""
            QScrollArea {{ background: {theme.CARD_BG};
                border: 1px solid {theme.CARD_BORDER}; border-radius: {theme.RADIUS_SM}px; }}
        """)
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        iv = QVBoxLayout(inner)
        iv.setContentsMargins(8, 8, 8, 8)
        iv.setSpacing(4)

        combos: list[QComboBox] = []
        for i in range(n - 1):
            row = QWidget()
            row.setStyleSheet("background: transparent;")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(8)
            lbl = QLabel(f"Cut {i+1} → {i+2}")
            lbl.setFixedWidth(96)
            lbl.setFont(QFont(theme.FONT_FAMILY, theme.FONT_SIZE_BASE))
            lbl.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
            rl.addWidget(lbl)
            cb = QComboBox()
            cb.addItems(TRANSITIONS)
            val = self._manual_cuts[i] if i < len(self._manual_cuts) else "fade"
            idx = TRANSITIONS.index(val) if val in TRANSITIONS else 0
            cb.setCurrentIndex(idx)
            cb.setStyleSheet(f"""
                QComboBox {{ background: {theme.INPUT_BG}; color: {theme.TEXT_PRIMARY};
                    border: 1px solid {theme.INPUT_BORDER}; border-radius: {theme.RADIUS_SM}px;
                    padding: 4px 8px; }}
                QComboBox QAbstractItemView {{
                    background: {theme.BG_SURFACE}; color: {theme.TEXT_PRIMARY};
                    border: 1px solid {theme.BORDER};
                    selection-background-color: {theme.ACCENT_LIGHT};
                    selection-color: {theme.TEXT_PRIMARY};
                }}
            """)
            rl.addWidget(cb, stretch=1)
            combos.append(cb)
            iv.addWidget(row)

        scroll.setWidget(inner)
        dv.addWidget(scroll, stretch=1)

        save_btn = QPushButton("Save cuts")
        save_btn.setFixedWidth(120)
        save_btn.setStyleSheet(f"""
            QPushButton {{ background: {theme.BTN_PRIMARY_BG}; color: {theme.BTN_PRIMARY_TEXT};
                border: none; border-radius: {theme.RADIUS_SM}px; padding: 8px 16px;
                font-weight: bold; }}
            QPushButton:hover {{ background: {theme.BTN_PRIMARY_HOVER}; }}
        """)
        save_btn.clicked.connect(dlg.accept)

        btn_row = QWidget()
        btn_hl = QHBoxLayout(btn_row)
        btn_hl.setContentsMargins(0, 0, 0, 0)
        btn_hl.addStretch()
        btn_hl.addWidget(save_btn)
        dv.addWidget(btn_row)

        if dlg.exec():
            self._manual_cuts = [c.currentText() for c in combos]

    # ── Create video ────────────────────────────────────────────────────────
    def _create_video(self):
        if not self._image_paths:
            self.app.set_status("⚠  Select a folder containing images"); return
        audio = self._audio_entry.text().strip()
        if not audio or not Path(audio).exists():
            self.app.set_status("⚠  Select a valid audio file"); return
        if not self._output_entry.text().strip():
            self.app.set_status("⚠  Specify where to save the video"); return
        from video.transcribe import parse_prompt_timestamp
        _prompts_for_check = [p for _, p in self.app.image_prompt_pairs] if self.app.image_prompt_pairs else []
        _has_embedded_timestamps = (
            len(_prompts_for_check) == len(self._image_paths) and len(_prompts_for_check) > 0
            and all(parse_prompt_timestamp(p) is not None for p in _prompts_for_check)
        )
        if not _has_embedded_timestamps:
            if self._rb_smart.isChecked() and not self._dg_key_entry.text().strip():
                self.app.set_status("⚠  Deepgram API key required for Smart timing"); return
            if self._rb_smart_manual.isChecked() and not self._transcript_area.toPlainText().strip():
                self.app.set_status("⚠  Paste a transcript to use Manual Smart timing"); return

        if self._cap_enable.isChecked() and not (
            self._dg_key_entry.text().strip() or self._transcript_area.toPlainText().strip()
        ):
            self.app.set_status(
                "⚠  Captions need word timing — provide a Deepgram key or paste a transcript"
            ); return

        self.app.config["deepgram_key"] = self._dg_key_entry.text().strip()
        self.app.config["llm_key"]      = self._llm_key_entry.text().strip()
        self.app.save_settings()

        llm_key = self._llm_key_entry.text().strip()
        if self._rb_groq.isChecked():
            llm_base, default_model = GROQ_BASE, GROQ_MODEL
        elif self._rb_openrouter.isChecked():
            llm_base, default_model = OPENROUTER_BASE, OPENROUTER_MODEL
        else:
            llm_base, default_model = OPENAI_BASE, OPENAI_MODEL
        llm_model = self._llm_model_entry.text().strip() or default_model

        self._create_btn.setEnabled(False)
        self._progress_bar.setValue(0)
        self._video_status_lbl.setText("Starting…")
        self._video_status_lbl.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        self._log_view.clear()
        self._log_view.setVisible(True)

        # Determine transition
        if self._rb_trans_fixed.isChecked():
            tm, tc = "fixed", self._fixed_trans_combo.currentText()
        elif self._rb_trans_random.isChecked():
            chosen = [t for t, cb in self._rand_checks.items() if cb.isChecked()]
            tm, tc = "random", (chosen if chosen else ["fade"])
        else:
            tm, tc = "manual", self._manual_cuts

        # Zoom
        zoom_mode = next(
            (v for v, rb in self._zoom_rbs.items() if rb.isChecked()), "none"
        )
        zoom_intensity = self._zoom_slider.value() / 100.0

        # Prompts for context-aware timing
        prompts = [p for _, p in self.app.image_prompt_pairs] if self.app.image_prompt_pairs else None

        if self._rb_smart.isChecked():
            t_mode = "smart_deepgram"
        elif self._rb_smart_manual.isChecked():
            t_mode = "smart_manual"
        elif self._rb_equal.isChecked():
            t_mode = "equal"
        else:
            t_mode = "fixed"

        self._worker = _VideoWorker(
            images=self._image_paths,
            audio=self._audio_entry.text().strip(),
            output=self._output_entry.text().strip(),
            timing_mode=t_mode,
            manual_transcript=self._transcript_area.toPlainText().strip(),
            dg_key=self._dg_key_entry.text().strip(),
            llm_key=llm_key,
            llm_base=llm_base,
            llm_model=llm_model,
            fixed_sec=float(self._fixed_sec_entry.text() or "4.0"),
            trans_mode=tm, trans_choice=tc,
            ratio="16:9" if self._rb_169.isChecked() else "9:16",
            trans_dur=float(self._trans_dur_entry.text() or "0.5"),
            zoom_mode=zoom_mode,
            zoom_intensity=zoom_intensity,
            prompts=prompts,
            captions_enabled=self._cap_enable.isChecked(),
            cap_font=self._cap_font_combo.currentText() or "Segoe UI",
            cap_size=self._cap_size_spin.value(),
            cap_bold=self._cap_bold_chk.isChecked(),
            cap_position=self._cap_position_combo.currentText(),
            cap_outline_width=float(self._cap_outline_spin.value()),
            cap_text_color=(self._cap_text_qcolor.red(), self._cap_text_qcolor.green(), self._cap_text_qcolor.blue()),
            cap_highlight_color=(self._cap_highlight_qcolor.red(), self._cap_highlight_qcolor.green(), self._cap_highlight_qcolor.blue()),
            cap_outline_color=(self._cap_outline_qcolor.red(), self._cap_outline_qcolor.green(), self._cap_outline_qcolor.blue()),
            cap_margin=80,
        )
        self._worker.progress.connect(self.on_video_progress)
        self._worker.done.connect(self.on_video_done)
        self._worker.error.connect(self.on_video_error)
        self._worker.start()

    # ── Callbacks ───────────────────────────────────────────────────────────
    def on_video_progress(self, msg: str):
        self._video_status_lbl.setText(msg[:80])
        self._video_status_lbl.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        self._log_view.append(msg)
        self._log_view.verticalScrollBar().setValue(self._log_view.verticalScrollBar().maximum())
        if "time=" in msg:
            self._progress_bar.setValue(50)

    def on_video_done(self, path: str):
        self._create_btn.setEnabled(True)
        self._progress_bar.setValue(100)
        self._video_status_lbl.setText("✓  Video saved successfully")
        self._video_status_lbl.setStyleSheet(f"color: {theme.SUCCESS};")
        self.app.set_status(f"Done — video saved to {path}")
        self.app.show_toast("Video created successfully", path)
        subprocess.Popen(["explorer", "/select,", path.replace("/", "\\")])

    def on_video_error(self, msg: str):
        self._create_btn.setEnabled(True)
        self._progress_bar.setValue(0)
        self._video_status_lbl.setText(f"Error — {msg[:70]}")
        self._video_status_lbl.setStyleSheet(f"color: {theme.DANGER};")
        self._log_view.append(f"\n=== ERROR ===\n{msg}")
        self._log_view.setVisible(True)
        self._log_view.verticalScrollBar().setValue(self._log_view.verticalScrollBar().maximum())
        self.app.set_status(f"Video error: {msg[:80]}")
