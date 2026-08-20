import threading
import queue
from pathlib import Path
from typing import Callable

from playwright.sync_api import sync_playwright, Page
from automation.flow_automation import generate_one

FLOW_URL = "https://labs.google/fx/tools/flow"

# Persistent profile folder — user logs in to Google once, stays logged in forever
_PROFILE_DIR = Path.home() / ".vse_browser_profile"


def _launch_browser(p):
    """
    Launch a browser using the best available channel.
    Tries Chrome first (user preference), then Edge, then playwright's Chromium.
    Returns (context, is_persistent_context).
    """
    profile_dir = str(_PROFILE_DIR)
    _PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    launch_args = ["--disable-blink-features=AutomationControlled", "--start-maximized"]

    # Try Chrome first, then Edge (both are Chromium-based on Windows)
    for channel in ("chrome", "msedge"):
        try:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                channel=channel,
                headless=False,
                args=launch_args,
                # Prevent playwright from adding --no-sandbox which triggers Chrome's warning
                ignore_default_args=["--no-sandbox"],
            )
            ctx.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            return ctx, True
        except Exception:
            continue

    # Fallback: playwright's bundled Chromium (no persistent profile)
    browser = p.chromium.launch(headless=False, args=launch_args)
    ctx = browser.new_context(no_viewport=True)
    ctx.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return ctx, False


class BrowserWorker:
    """
    Manages a persistent Playwright browser for Google Flow automation.
    All Playwright calls happen on a single dedicated thread.
    Uses the user's installed Edge/Chrome so it works reliably on Windows.
    """

    def __init__(self):
        self._page: Page | None = None
        self._error: str | None = None
        self._cmd_queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    # ── public API (called from main/UI thread) ──────────────────────────────

    def open_flow(self) -> bool:
        """Open Google Flow in the browser. Returns True on success, False on error."""
        event = threading.Event()
        self._cmd_queue.put(("open", event))
        opened = event.wait(timeout=45)
        if not opened:
            self._error = "Browser timed out after 45 seconds"
        return opened and self._error is None

    def run_batch(
        self,
        prompts: list[str],
        output_dir: Path,
        emit: Callable,
        should_continue: Callable[[], bool],
    ):
        """Submit each prompt and download the generated image. Runs synchronously."""
        event = threading.Event()
        self._cmd_queue.put(("batch", prompts, output_dir, emit, should_continue, event))
        event.wait()

    def close(self):
        self._cmd_queue.put(("quit",))

    # ── internal worker thread ────────────────────────────────────────────────

    def _worker(self):
        try:
            with sync_playwright() as p:
                context, _persistent = _launch_browser(p)
                self._page = context.new_page() if not context.pages else context.pages[0]

                while True:
                    cmd = self._cmd_queue.get()
                    kind = cmd[0]

                    if kind == "open":
                        event: threading.Event = cmd[1]
                        try:
                            self._page.goto(FLOW_URL, wait_until="domcontentloaded", timeout=30000)
                        except Exception:
                            # Browser is visible; user can navigate manually if needed
                            pass
                        event.set()

                    elif kind == "batch":
                        _, prompts, output_dir, emit, should_continue, event = cmd
                        self._run_batch(prompts, output_dir, emit, should_continue)
                        event.set()

                    elif kind == "quit":
                        try:
                            context.close()
                        except Exception:
                            pass
                        break

        except Exception as e:
            self._error = str(e)
            self._drain_queue()

    def _drain_queue(self):
        """Unblock any callers waiting on events so they don't hang forever."""
        while True:
            try:
                cmd = self._cmd_queue.get_nowait()
                if cmd[0] == "open":
                    cmd[1].set()
                elif cmd[0] == "batch":
                    cmd[-1].set()
            except queue.Empty:
                break

    def _run_batch(self, prompts, output_dir, emit, should_continue):
        saved_paths = []
        total = len(prompts)

        for i, prompt in enumerate(prompts):
            if not should_continue():
                emit("status", "Stopped by user")
                break

            emit("status", f"Generating image {i+1}/{total}…")

            out_file = output_dir / f"image_{i+1:04d}.jpg"

            try:
                ok = generate_one(self._page, prompt, out_file)
            except Exception as e:
                emit("batch_error", f"Error on prompt {i+1}: {e}")
                return

            if ok:
                saved_paths.append(out_file)
                emit("progress", i + 1, total)
                emit("image_ready", str(out_file), prompt)
            else:
                emit("status", f"Image {i+1} failed — skipping")

        emit("batch_done", [str(p) for p in saved_paths])
