"""
FFmpeg-based video stitcher.

Technique: filter_complex with xfade transitions.
Each image is loaded as a video clip (-loop 1 -t duration).
xfade blends consecutive clips with the chosen transition effect.
Optional Ken Burns zoom (zoompan) applied per clip before xfade.
Final output is H.264 MP4 with AAC audio.
"""

import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

TRANSITIONS = [
    "fade", "fadeblack", "fadewhite", "dissolve", "pixelize",
    "wipeleft", "wiperight", "wipeup", "wipedown",
    "slideleft", "slideright", "slideup", "slidedown",
    "zoomin", "radial", "circlecrop",
]

ZOOM_MODES = ["none", "zoom_in", "zoom_out", "random"]


def _ffmpeg_path() -> tuple[str, str]:
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS  # type: ignore[attr-defined]
        return os.path.join(base, "assets", "ffmpeg.exe"), os.path.join(base, "assets", "ffprobe.exe")
    base = Path(__file__).parent.parent / "assets"
    ff = base / "ffmpeg.exe"
    fp = base / "ffprobe.exe"
    return (str(ff) if ff.exists() else "ffmpeg"), (str(fp) if fp.exists() else "ffprobe")


def get_audio_duration(audio_path: Path) -> float:
    _, ffprobe = _ffmpeg_path()
    result = subprocess.run(
        [ffprobe, "-v", "quiet", "-print_format", "json", "-show_format", str(audio_path)],
        capture_output=True, text=True,
    )
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


# zoompan crops on integer source pixels each frame. If the source is already
# downscaled to the output resolution, that crop-window shrink is only ~1-2px
# per frame, and the rounding shows up as visible micro-jumps ("shaking").
# Supersampling the source above the output size before zoompan runs moves
# that rounding error far below one output pixel once zoompan's own resize
# blends it back down. Kept at 3x for maximum smoothness — the OOM risk with
# many images is bounded by -filter_complex_threads=1 below instead, which
# serializes branch execution so peak memory no longer scales with image count.
ZOOM_SUPERSAMPLE = 3


def _zoom_filter(mode: str, frames: int, width: int, height: int, intensity: float) -> str:
    """
    Ken Burns via zoompan, driven off `on` (output frame counter) so there is
    zero accumulated floating-point error frame-to-frame — only the easing
    curve below shapes the motion.

    Uses a smoothstep ease-in/ease-out curve (t*t*(3-2t)) instead of linear
    interpolation, so the zoom eases in and out organically instead of
    moving at a constant mechanical speed.
    """
    denom = max(frames - 1, 1)
    t = f"(on/{denom})"
    if mode == "zoom_out":
        t = f"(1-{t})"
    eased = f"({t}*{t}*(3-2*{t}))"
    z_expr = f"1+{intensity:.4f}*{eased}"
    return (
        f"zoompan=z='{z_expr}':"
        f"x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':"
        f"d={frames}:s={width}x{height}:fps=25"
    )


def _ffmpeg_escape_path(path: Path) -> str:
    """Escape a filesystem path for use inside an ffmpeg filter argument."""
    p = str(path).replace("\\", "/")
    p = p.replace(":", "\\:")
    return p


def stitch_video(
    image_paths: list[Path],
    audio_path: Path,
    output_path: Path,
    segments: list[dict],
    transition_mode: str,
    transition_choice,
    aspect_ratio: str,
    transition_duration: float = 0.5,
    zoom_mode: str = "none",
    zoom_intensity: float = 0.20,
    audio_duration: float | None = None,
    captions_ass_path: Path | None = None,
    on_progress: Callable | None = None,
) -> bool:

    ffmpeg, _ = _ffmpeg_path()
    n = len(image_paths)
    if n == 0:
        raise ValueError("No images to stitch.")

    width, height = (1920, 1080) if aspect_ratio == "16:9" else (1080, 1920)

    # Each clip is extended by transition_duration (except the last) so xfade has overlap frames
    durations = [
        seg["duration"] + (transition_duration if i < n - 1 else 0.0)
        for i, seg in enumerate(segments)
    ]

    # Resolve per-cut transitions
    cuts = n - 1
    transitions_per_cut: list[str] = []
    for i in range(cuts):
        if transition_mode == "fixed":
            transitions_per_cut.append(str(transition_choice))
        elif transition_mode == "random":
            pool = list(transition_choice) if transition_choice else ["fade"]
            transitions_per_cut.append(random.choice(pool))
        else:
            tc = list(transition_choice)
            transitions_per_cut.append(tc[i] if i < len(tc) else "fade")

    # Windows' CreateProcess caps the total command line at ~32,767 characters.
    # With many images, N copies of the user's (often long) original folder
    # path is what actually blows this budget, not FFmpeg or this app.
    # Hardlinking every image to a short numbered name in a temp folder costs
    # nothing (no data is copied — it's the same file on disk under a second
    # name) and shrinks each `-i` argument to a small, constant length
    # regardless of how deep the source folder is nested.
    short_dir = Path(tempfile.mkdtemp(prefix="vse_imgs_"))
    filter_script_name: str | None = None
    try:
        short_paths: list[Path] = []
        for i, img in enumerate(image_paths):
            short = short_dir / f"{i}{img.suffix.lower()}"
            try:
                os.link(img, short)
            except OSError:
                shutil.copy2(img, short)
            short_paths.append(short)

        # Build inputs
        cmd = [ffmpeg, "-y"]
        for img, dur in zip(short_paths, durations):
            cmd += ["-loop", "1", "-t", f"{dur:.4f}", "-i", str(img)]
        cmd += ["-i", str(audio_path)]

        # Scale+pad each image to exact output size
        scale_base = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
            f"setsar=1"
        )

        # Supersampled scale+pad used only for the zoom branch — see ZOOM_SUPERSAMPLE.
        ss_w, ss_h = width * ZOOM_SUPERSAMPLE, height * ZOOM_SUPERSAMPLE
        scale_base_ss = (
            f"scale={ss_w}:{ss_h}:force_original_aspect_ratio=decrease,"
            f"pad={ss_w}:{ss_h}:(ow-iw)/2:(oh-ih)/2:black,"
            f"setsar=1"
        )

        # Per-clip frame counts via a running accumulator, not independent
        # per-clip rounding. `int(dur * 25)` always truncates (never rounds
        # up), so every single clip loses up to 1/25s — with hundreds of
        # images that bias compounds into real, growing lag between the
        # audio/captions and what image is actually on screen. Tracking the
        # cumulative *ideal* frame position and deriving each clip's frame
        # count as the gap to the next rounded target keeps total drift
        # bounded to under one frame for the entire video, regardless of
        # image count.
        FPS = 25
        frame_counts: list[int] = []
        cum_ideal = 0.0
        cum_actual = 0
        for dur in durations:
            cum_ideal += dur * FPS
            target_total = round(cum_ideal)
            frames_i = max(2, target_total - cum_actual)
            frame_counts.append(frames_i)
            cum_actual += frames_i

        filters: list[str] = []
        for i, dur in enumerate(durations):
            frames = frame_counts[i]
            zm = zoom_mode
            if zm == "random":
                zm = random.choice(["zoom_in", "zoom_out"])
            if zm != "none":
                zoom_f = _zoom_filter(zm, frames, width, height, zoom_intensity)
                filters.append(f"[{i}:v]{scale_base_ss},{zoom_f}[v{i}]")
            else:
                filters.append(f"[{i}:v]{scale_base},fps=25,trim=end_frame={frames}[v{i}]")

        # If burning captions, the xfade/copy chain feeds an intermediate label
        # and the subtitles filter produces the final [vout] instead.
        final_label = "vraw" if captions_ass_path else "vout"

        # Chain xfade transitions
        cumulative = 0.0
        prev = "v0"
        for i in range(cuts):
            cumulative += segments[i]["duration"]
            label = final_label if i == cuts - 1 else f"x{i+1}"
            filters.append(
                f"[{prev}][v{i+1}]xfade=transition={transitions_per_cut[i]}:"
                f"duration={transition_duration:.3f}:offset={cumulative:.4f}[{label}]"
            )
            prev = label

        if n == 1:
            filters.append(f"[v0]copy[{final_label}]")

        if captions_ass_path:
            escaped = _ffmpeg_escape_path(captions_ass_path)
            filters.append(f"[{final_label}]subtitles=filename='{escaped}'[vout]")

        tail = ["-t", f"{audio_duration:.4f}"] if audio_duration else ["-shortest"]

        # With many images, the inline filter_complex string (one zoompan/scale
        # chain per image) can push the total command line past Windows'
        # ~32,767-character CreateProcess limit, failing with WinError 206
        # ("filename or extension too long" — actually the whole command line).
        # Writing the filter graph to a script file sidesteps that limit entirely.
        filter_script = tempfile.NamedTemporaryFile(
            mode="w", suffix=".ffconcat", delete=False, encoding="utf-8"
        )
        filter_script_name = filter_script.name
        filter_script.write(";\n".join(filters))
        filter_script.close()

        cmd += [
            "-filter_complex_threads", "1",
            "-filter_complex_script", filter_script.name,
            "-map", "[vout]",
            "-map", f"{n}:a",
            "-c:v", "libx264", "-preset", "fast",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            *tail,
            str(output_path),
        ]

        if on_progress:
            on_progress(f"Running FFmpeg ({n} images, {cuts} transitions)…")

        recent_lines: list[str] = []
        proc = subprocess.Popen(
            cmd, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
        )
        for line in proc.stderr:  # type: ignore[union-attr]
            line = line.strip()
            if line:
                recent_lines.append(line)
                if len(recent_lines) > 30:
                    recent_lines.pop(0)
                if on_progress:
                    on_progress(line[:80])
        proc.wait()
        if proc.returncode != 0:
            tail = "\n".join(recent_lines[-15:])
            raise RuntimeError(f"FFmpeg exited with code {proc.returncode}:\n{tail}")
        return True
    finally:
        if filter_script_name:
            try:
                os.unlink(filter_script_name)
            except OSError:
                pass
        shutil.rmtree(short_dir, ignore_errors=True)
