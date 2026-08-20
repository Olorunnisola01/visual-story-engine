"""
Karaoke-style burned-in captions.

Builds a .ass subtitle file — one Dialogue event per word, where the
currently-spoken word is wrapped in a highlight-color override tag and the
rest of its caption line stays in the default text color. Rendered by
libass, which is compiled into virtually every standard FFmpeg build
(including the one bundled with this app) — no external API, no cost.
"""

from pathlib import Path

_ALIGN = {"bottom": 2, "middle": 5, "top": 8}


def _ass_color(rgb: tuple[int, int, int]) -> str:
    """ASS/SSA colors are &HAABBGGRR — alpha 00 = fully opaque."""
    r, g, b = rgb
    return f"&H00{b:02X}{g:02X}{r:02X}&"


def _fmt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def group_words_into_lines(
    words: list[dict],
    max_chars: int = 34,
    max_words: int = 7,
) -> list[list[dict]]:
    """Group consecutive words into readable caption-line chunks."""
    lines: list[list[dict]] = []
    current: list[dict] = []
    current_len = 0
    for w in words:
        wl = len(w["word"]) + 1
        if current and (current_len + wl > max_chars or len(current) >= max_words):
            lines.append(current)
            current, current_len = [], 0
        current.append(w)
        current_len += wl
    if current:
        lines.append(current)
    return lines


def build_ass_file(
    words: list[dict],
    output_path: Path,
    video_w: int,
    video_h: int,
    font_family: str = "Arial",
    font_size: int = 48,
    text_color: tuple[int, int, int] = (255, 255, 255),
    highlight_color: tuple[int, int, int] = (255, 214, 0),
    outline_color: tuple[int, int, int] = (0, 0, 0),
    outline_width: float = 3.0,
    position: str = "bottom",
    margin_v: int = 80,
    bold: bool = True,
) -> Path:
    """
    Write a .ass file with one Dialogue event per word. Each event shows the
    full current caption line, with only the active word wrapped in a
    highlight-color override tag — giving a moving word-by-word highlight
    instead of a classic karaoke fill-sweep.
    """
    align = _ALIGN.get(position, 2)
    primary = _ass_color(text_color)
    highlight = _ass_color(highlight_color)
    outline = _ass_color(outline_color)

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {video_w}\n"
        f"PlayResY: {video_h}\n"
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Caption,{font_family},{font_size},{primary},{primary},{outline},"
        f"&H00000000,{-1 if bold else 0},0,0,0,100,100,0,0,1,{outline_width:.1f},0,"
        f"{align},40,40,{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    lines = group_words_into_lines(words)
    events: list[str] = []
    for line in lines:
        n = len(line)
        for i, w in enumerate(line):
            start = w["start"]
            end = line[i + 1]["start"] if i + 1 < n else w["end"]
            end = max(end, start + 0.05)

            parts = []
            for j, w2 in enumerate(line):
                if j == i:
                    parts.append(f"{{\\c{highlight}}}{w2['word']}{{\\c{primary}}}")
                else:
                    parts.append(w2["word"])
            text_line = " ".join(parts)

            events.append(
                f"Dialogue: 0,{_fmt_time(start)},{_fmt_time(end)},Caption,,0,0,0,,{text_line}"
            )

    output_path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return output_path


_PREVIEW_SAMPLE_WORDS = [
    {"word": "THE",   "start": 0.0, "end": 0.35},
    {"word": "QUICK", "start": 0.35, "end": 0.75},
    {"word": "BROWN", "start": 0.75, "end": 1.15},
    {"word": "FOX",   "start": 1.15, "end": 1.45},
    {"word": "JUMPS", "start": 1.45, "end": 1.85},
]
_PREVIEW_SEEK = 0.9  # lands inside "BROWN" — a mid-line word, not the first


def render_preview_frame(
    output_png: Path,
    video_w: int,
    video_h: int,
    background_image: Path | None,
    font_family: str = "Arial",
    font_size: int = 48,
    text_color: tuple[int, int, int] = (255, 255, 255),
    highlight_color: tuple[int, int, int] = (255, 214, 0),
    outline_color: tuple[int, int, int] = (0, 0, 0),
    outline_width: float = 3.0,
    position: str = "bottom",
    margin_v: int = 80,
    bold: bool = True,
) -> Path:
    """
    Render one still frame through the exact same FFmpeg + libass pipeline
    used for the real burned-in captions, at the real output resolution —
    so the live preview is pixel-identical to what the final render
    produces, not a Qt-drawn approximation of it.

    Reuses a fixed temp filename for the intermediate .ass file so repeated
    preview updates (every time a control changes) never accumulate files.
    """
    import subprocess
    import tempfile
    from video.stitcher import _ffmpeg_path, _ffmpeg_escape_path

    ass_path = Path(tempfile.gettempdir()) / "vse_caption_preview.ass"
    build_ass_file(
        _PREVIEW_SAMPLE_WORDS, ass_path, video_w, video_h,
        font_family=font_family, font_size=font_size,
        text_color=text_color, highlight_color=highlight_color,
        outline_color=outline_color, outline_width=outline_width,
        position=position, margin_v=margin_v, bold=bold,
    )

    ffmpeg, _ = _ffmpeg_path()
    escaped = _ffmpeg_escape_path(ass_path)

    if background_image and Path(background_image).exists():
        vf = (
            f"scale={video_w}:{video_h}:force_original_aspect_ratio=decrease,"
            f"pad={video_w}:{video_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,"
            f"subtitles=filename='{escaped}'"
        )
        cmd = [
            ffmpeg, "-y", "-loop", "1", "-i", str(background_image),
            "-vf", vf, "-ss", f"{_PREVIEW_SEEK}", "-frames:v", "1", str(output_png),
        ]
    else:
        vf = f"subtitles=filename='{escaped}'"
        cmd = [
            ffmpeg, "-y", "-f", "lavfi",
            "-i", f"color=c=0x1a1a1a:s={video_w}x{video_h}:d=2",
            "-vf", vf, "-ss", f"{_PREVIEW_SEEK}", "-frames:v", "1", str(output_png),
        ]

    subprocess.run(cmd, capture_output=True, timeout=15)
    return output_png
