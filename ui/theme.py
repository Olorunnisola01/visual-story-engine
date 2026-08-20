# ─────────────────────────────────────────────────────────────
#  Design Tokens  —  Visual Story Engine  (White / Black Theme)
#  Clean editorial aesthetic — strong contrast, no decorative greys.
# ─────────────────────────────────────────────────────────────

# ── Raw palette ───────────────────────────────────────────────
WHITE    = "#FFFFFF"
BLACK    = "#0A0A0A"

GREY_900 = "#111111"
GREY_800 = "#1F2937"
GREY_700 = "#374151"
GREY_600 = "#4B5563"
GREY_500 = "#6B7280"
GREY_400 = "#9CA3AF"
GREY_200 = "#E5E7EB"
GREY_100 = "#F3F4F6"
GREY_50  = "#F9FAFB"

BLUE_700  = "#1D4ED8"
BLUE_600  = "#2563EB"
BLUE_100  = "#DBEAFE"
BLUE_50   = "#EFF6FF"

GREEN_700 = "#15803D"
GREEN_600 = "#16A34A"
GREEN_200 = "#BBF7D0"
GREEN_100 = "#DCFCE7"

RED_700  = "#B91C1C"
RED_600  = "#DC2626"
RED_200  = "#FECACA"
RED_100  = "#FEE2E2"

AMBER_600 = "#D97706"
AMBER_100 = "#FEF3C7"

# ── Semantic backgrounds ──────────────────────────────────────
BG_APP      = WHITE     # main window fill
BG_SURFACE  = WHITE     # cards, panels, header
BG_ELEVATED = GREY_50   # input fields, subtle recesses
BG_HOVER    = GREY_100  # hover on white surfaces

# ── Accent ────────────────────────────────────────────────────
ACCENT       = BLUE_600
ACCENT_HOVER = BLUE_700
ACCENT_LIGHT = BLUE_50

# ── Text — all dark, all readable ────────────────────────────
TEXT_PRIMARY   = BLACK     # #0A0A0A  main body
TEXT_SECONDARY = GREY_800  # #1F2937  labels, sub-headings
TEXT_MUTED     = GREY_600  # #4B5563  hints/captions (still legible)

# ── Borders ───────────────────────────────────────────────────
BORDER        = GREY_200
BORDER_STRONG = GREY_400
BORDER_SUBTLE = GREY_100

# ── Semantic ──────────────────────────────────────────────────
SUCCESS        = GREEN_600
SUCCESS_HOVER  = GREEN_700
SUCCESS_BG     = GREEN_100
SUCCESS_BORDER = GREEN_200

WARNING        = AMBER_600
WARNING_BG     = AMBER_100

DANGER        = RED_600
DANGER_HOVER  = RED_700
DANGER_BG     = RED_100
DANGER_BORDER = RED_200

# ── Buttons ───────────────────────────────────────────────────
BTN_PRIMARY_BG    = GREY_900   # solid black — editorial, high-impact
BTN_PRIMARY_HOVER = GREY_700
BTN_PRIMARY_TEXT  = WHITE

BTN_SECONDARY_BG     = WHITE
BTN_SECONDARY_HOVER  = GREY_100
BTN_SECONDARY_BORDER = GREY_200
BTN_SECONDARY_TEXT   = GREY_900

BTN_GHOST_BG    = WHITE
BTN_GHOST_HOVER = GREY_50
BTN_GHOST_TEXT  = GREY_700

BTN_DANGER_BG     = RED_100
BTN_DANGER_HOVER  = RED_600
BTN_DANGER_BORDER = RED_200
BTN_DANGER_TEXT   = RED_600

BTN_SUCCESS_BG    = GREEN_600
BTN_SUCCESS_HOVER = GREEN_700
BTN_SUCCESS_TEXT  = WHITE

BTN_DISABLED_BG   = GREY_100
BTN_DISABLED_TEXT = GREY_400

# ── Inputs ────────────────────────────────────────────────────
INPUT_BG           = WHITE
INPUT_BORDER       = GREY_200
INPUT_BORDER_FOCUS = BLUE_600
INPUT_TEXT         = BLACK
INPUT_PLACEHOLDER  = GREY_400

# ── Progress bar ──────────────────────────────────────────────
PROGRESS_TRACK = GREY_200
PROGRESS_FILL  = GREY_900

# ── Tab strip (light pill design) ────────────────────────────
TAB_TRAY      = GREY_100   # light container
TAB_SELECTED  = WHITE      # active pill lifts to white
TAB_SEL_HOVER = GREY_50
TAB_UNSEL     = GREY_100   # merges into tray
TAB_UNS_HOVER = GREY_200
TAB_TEXT      = GREY_900   # near-black reads on all light states
TAB_TEXT_DIM  = GREY_400

# ── Cards ─────────────────────────────────────────────────────
CARD_BG     = WHITE
CARD_BORDER = GREY_200

# ── Section labels ────────────────────────────────────────────
SECTION_LABEL_TEXT = GREY_700
SECTION_LABEL_SIZE = 10

# ── Typography ────────────────────────────────────────────────
FONT_FAMILY = "Segoe UI"
FONT_MONO   = "Consolas"

FONT_SIZE_XS   = 10
FONT_SIZE_SM   = 11
FONT_SIZE_BASE = 13
FONT_SIZE_MD   = 14
FONT_SIZE_LG   = 17

# ── Spacing (4 px grid) ───────────────────────────────────────
SP_1 =  4
SP_2 =  8
SP_3 = 12
SP_4 = 16
SP_5 = 20
SP_6 = 24

# ── Border radius ─────────────────────────────────────────────
RADIUS_SM =  6
RADIUS_MD = 10
RADIUS_LG = 14

# ── Qt / PySide6 stylesheet ───────────────────────────────────
QSS = f"""
QWidget {{
    background: {WHITE};
    color: {TEXT_PRIMARY};
    font-family: "Segoe UI";
    font-size: 13px;
    border: none;
    outline: none;
}}
QScrollBar:vertical {{
    background: {GREY_50};
    width: 8px;
    border-radius: 4px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {GREY_200};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {GREY_400};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
QScrollArea {{ background: {WHITE}; border: none; }}
QTabWidget::pane {{
    background: {WHITE};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_MD}px;
    top: -1px;
}}
QTabBar {{
    background: {TAB_TRAY};
    padding: 4px 8px;
}}
QTabBar::tab {{
    background: transparent;
    color: {TAB_TEXT};
    padding: 7px 22px;
    border-radius: {RADIUS_SM}px;
    margin: 1px 2px;
    min-width: 90px;
    font-size: 13px;
}}
QTabBar::tab:selected {{
    background: {TAB_SELECTED};
    color: {TAB_TEXT};
    font-weight: bold;
}}
QTabBar::tab:!selected:hover {{
    background: {TAB_UNS_HOVER};
}}
QPushButton[primary="true"] {{
    background: {BTN_PRIMARY_BG};
    color: {BTN_PRIMARY_TEXT};
    border-radius: {RADIUS_SM}px;
    padding: 8px 18px;
    font-weight: bold;
    font-size: 13px;
}}
QPushButton[primary="true"]:hover {{ background: {BTN_PRIMARY_HOVER}; }}
QPushButton[primary="true"]:disabled {{
    background: {BTN_DISABLED_BG};
    color: {BTN_DISABLED_TEXT};
}}
QPushButton[secondary="true"] {{
    background: {BTN_SECONDARY_BG};
    color: {BTN_SECONDARY_TEXT};
    border: 1px solid {BTN_SECONDARY_BORDER};
    border-radius: {RADIUS_SM}px;
    padding: 6px 14px;
    font-size: 12px;
}}
QPushButton[secondary="true"]:hover {{ background: {BTN_SECONDARY_HOVER}; }}
QLineEdit {{
    background: {INPUT_BG};
    color: {INPUT_TEXT};
    border: 1px solid {INPUT_BORDER};
    border-radius: {RADIUS_SM}px;
    padding: 6px 10px;
    font-size: 13px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus {{ border-color: {INPUT_BORDER_FOCUS}; }}
QLineEdit:disabled {{ color: {TEXT_MUTED}; }}
QTextEdit {{
    background: {BG_ELEVATED};
    color: {INPUT_TEXT};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_SM}px;
    padding: 8px;
    font-family: "Consolas";
    font-size: 13px;
    selection-background-color: {ACCENT};
}}
QTextEdit:focus {{ border-color: {INPUT_BORDER_FOCUS}; }}
QRadioButton {{
    color: {TEXT_PRIMARY};
    spacing: 8px;
    font-size: 13px;
    background: transparent;
}}
QRadioButton::indicator {{
    width: 16px; height: 16px;
    border-radius: 8px;
    border: 2px solid {BORDER_STRONG};
    background: {WHITE};
}}
QRadioButton::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}
QRadioButton::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox {{
    color: {TEXT_PRIMARY};
    spacing: 6px;
    font-size: 12px;
    background: transparent;
}}
QCheckBox::indicator {{
    width: 15px; height: 15px;
    border-radius: 4px;
    border: 2px solid {BORDER_STRONG};
    background: {WHITE};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}
QComboBox {{
    background: {INPUT_BG};
    color: {TEXT_PRIMARY};
    border: 1px solid {INPUT_BORDER};
    border-radius: {RADIUS_SM}px;
    padding: 5px 10px;
    font-size: 13px;
    min-width: 160px;
}}
QComboBox:focus, QComboBox:on {{ border-color: {INPUT_BORDER_FOCUS}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background: {BG_SURFACE};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_SM}px;
    selection-background-color: {ACCENT_LIGHT};
    selection-color: {TEXT_PRIMARY};
    padding: 4px;
    outline: none;
}}
QProgressBar {{
    background: {PROGRESS_TRACK};
    border: none;
    border-radius: 3px;
    height: 6px;
    text-align: center;
    font-size: 0px;
}}
QProgressBar::chunk {{
    background: {PROGRESS_FILL};
    border-radius: 3px;
}}
QSlider::groove:horizontal {{
    background: {PROGRESS_TRACK};
    height: 4px;
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {GREY_900};
    width: 16px; height: 16px;
    border-radius: 8px;
    margin: -6px 0;
}}
QSlider::handle:horizontal:hover {{ background: {ACCENT}; }}
QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 2px;
}}
"""
