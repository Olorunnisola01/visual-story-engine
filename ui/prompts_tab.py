import re
import threading
import tkinter as tk
from pathlib import Path
import customtkinter as ctk
from tkinter import filedialog

from automation.browser import BrowserWorker
from ui import theme


def parse_prompts(text: str) -> list[str]:
    blocks = re.split(r"\n[ \t]*\n", text.strip())
    return [b.strip() for b in blocks if b.strip()]


def _section_label(parent, text: str):
    """Small uppercase section heading."""
    return ctk.CTkLabel(
        parent, text=text,
        font=ctk.CTkFont(family=theme.FONT_FAMILY, size=theme.FONT_SIZE_XS, weight="bold"),
        text_color=theme.SECTION_LABEL_TEXT,
    )


def _card(parent, title: str):
    """White card with border. Returns (outer, inner)."""
    outer = ctk.CTkFrame(
        parent,
        fg_color=theme.CARD_BG,
        corner_radius=theme.RADIUS_MD,
        border_color=theme.CARD_BORDER,
        border_width=1,
    )
    _section_label(outer, title).pack(anchor="w", padx=theme.SP_4, pady=(theme.SP_3, theme.SP_2))
    sep = ctk.CTkFrame(outer, height=1, fg_color=theme.BORDER, corner_radius=0)
    sep.pack(fill="x", padx=0)
    inner = ctk.CTkFrame(outer, fg_color="transparent")
    inner.pack(fill="both", expand=True, padx=theme.SP_4, pady=theme.SP_3)
    return outer, inner


HINT = (
    "Enter one prompt per block — separate each with a blank line.\n\n"
    "Example:\n"
    "A serene forest at dawn with golden light filtering through the trees\n\n"
    "A bustling Tokyo street at night, neon reflections on rain-soaked pavement"
)


class PromptsTab(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self._browser: BrowserWorker | None = None
        self._running  = False
        self._has_hint = True
        self.pack(fill="both", expand=True, padx=theme.SP_4, pady=theme.SP_4)
        self._build()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ── Setup card ────────────────────────────────────────────────────────
        setup_outer, setup = _card(self, "SETUP")
        setup_outer.grid(row=0, column=0, sticky="ew", pady=(0, theme.SP_3))
        setup.grid_columnconfigure(2, weight=1)

        # Row: Browser controls
        ctk.CTkLabel(
            setup, text="Browser",
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=theme.FONT_SIZE_BASE),
            text_color=theme.TEXT_SECONDARY, width=76, anchor="w",
        ).grid(row=0, column=0, sticky="w", pady=(0, theme.SP_2))

        self._open_btn = ctk.CTkButton(
            setup, text="Open Google Flow", width=180,
            fg_color=theme.BTN_PRIMARY_BG,
            hover_color=theme.BTN_PRIMARY_HOVER,
            text_color=theme.BTN_PRIMARY_TEXT,
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=theme.FONT_SIZE_BASE),
            corner_radius=theme.RADIUS_SM,
            command=self._open_browser,
        )
        self._open_btn.grid(row=0, column=1, padx=(0, theme.SP_3), pady=(0, theme.SP_2))

        self._login_btn = ctk.CTkButton(
            setup, text="✓  I'm Logged In", width=158,
            fg_color=theme.BTN_SECONDARY_BG,
            hover_color=theme.BTN_SECONDARY_HOVER,
            border_color=theme.BTN_SECONDARY_BORDER, border_width=1,
            text_color=theme.TEXT_MUTED,
            state="disabled",
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=theme.FONT_SIZE_BASE),
            corner_radius=theme.RADIUS_SM,
            command=self._confirm_login,
        )
        self._login_btn.grid(row=0, column=2, sticky="w", pady=(0, theme.SP_2))

        # Row: Output folder
        ctk.CTkLabel(
            setup, text="Save to",
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=theme.FONT_SIZE_BASE),
            text_color=theme.TEXT_SECONDARY, width=76, anchor="w",
        ).grid(row=1, column=0, sticky="w")

        folder_row = ctk.CTkFrame(setup, fg_color="transparent")
        folder_row.grid(row=1, column=1, columnspan=2, sticky="ew")
        folder_row.grid_columnconfigure(0, weight=1)

        self._out_var = tk.StringVar(value=self.app.config.get("last_output_dir", ""))
        ctk.CTkEntry(
            folder_row, textvariable=self._out_var,
            placeholder_text="Choose output folder…",
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=theme.FONT_SIZE_BASE),
            fg_color=theme.INPUT_BG,
            border_color=theme.INPUT_BORDER,
            text_color=theme.INPUT_TEXT,
            corner_radius=theme.RADIUS_SM,
        ).grid(row=0, column=0, sticky="ew", padx=(0, theme.SP_2))

        ctk.CTkButton(
            folder_row, text="Browse", width=84,
            fg_color=theme.BTN_SECONDARY_BG,
            hover_color=theme.BTN_SECONDARY_HOVER,
            border_color=theme.BTN_SECONDARY_BORDER, border_width=1,
            text_color=theme.BTN_SECONDARY_TEXT,
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=theme.FONT_SIZE_BASE),
            corner_radius=theme.RADIUS_SM,
            command=self._browse_out,
        ).grid(row=0, column=1)

        # ── Prompt input card ─────────────────────────────────────────────────
        prompt_outer = ctk.CTkFrame(
            self,
            fg_color=theme.CARD_BG,
            corner_radius=theme.RADIUS_MD,
            border_color=theme.CARD_BORDER,
            border_width=1,
        )
        prompt_outer.grid(row=1, column=0, sticky="nsew", pady=(0, theme.SP_3))
        prompt_outer.grid_columnconfigure(0, weight=1)
        prompt_outer.grid_rowconfigure(1, weight=1)

        # Card header row
        ph = ctk.CTkFrame(prompt_outer, fg_color="transparent")
        ph.grid(row=0, column=0, sticky="ew", padx=theme.SP_4, pady=(theme.SP_3, 0))
        ph.grid_columnconfigure(0, weight=1)

        _section_label(ph, "PROMPTS").grid(row=0, column=0, sticky="w")

        self._count_label = ctk.CTkLabel(
            ph, text="0 prompts",
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=theme.FONT_SIZE_SM),
            text_color=theme.TEXT_MUTED,
        )
        self._count_label.grid(row=0, column=1, sticky="e")

        sep = ctk.CTkFrame(prompt_outer, height=1, fg_color=theme.BORDER, corner_radius=0)
        sep.grid(row=1, column=0, sticky="ew", pady=(theme.SP_2, 0))

        self._prompt_box = ctk.CTkTextbox(
            prompt_outer,
            font=ctk.CTkFont(family=theme.FONT_MONO, size=theme.FONT_SIZE_BASE),
            fg_color=theme.BG_ELEVATED,
            border_color=theme.BORDER,
            border_width=1,
            corner_radius=theme.RADIUS_SM,
            text_color=theme.TEXT_MUTED,
            wrap="word",
        )
        self._prompt_box.grid(row=2, column=0, sticky="nsew",
                               padx=theme.SP_4, pady=theme.SP_3)
        prompt_outer.grid_rowconfigure(2, weight=1)

        self._prompt_box.insert("1.0", HINT)
        self._prompt_box.bind("<FocusIn>",    self._clear_hint)
        self._prompt_box.bind("<FocusOut>",   self._restore_hint)
        self._prompt_box.bind("<KeyRelease>",  lambda e: self._update_count())

        # ── Action bar ────────────────────────────────────────────────────────
        action = ctk.CTkFrame(
            self,
            fg_color=theme.CARD_BG,
            corner_radius=theme.RADIUS_MD,
            border_color=theme.CARD_BORDER,
            border_width=1,
        )
        action.grid(row=2, column=0, sticky="ew")
        action.grid_columnconfigure(0, weight=1)

        self._progress_bar = ctk.CTkProgressBar(
            action, height=5, corner_radius=3,
            fg_color=theme.PROGRESS_TRACK,
            progress_color=theme.PROGRESS_FILL,
        )
        self._progress_bar.set(0)
        self._progress_bar.grid(row=0, column=0, columnspan=2, sticky="ew",
                                 padx=theme.SP_4, pady=(theme.SP_3, theme.SP_2))

        self._progress_label = ctk.CTkLabel(
            action, text="",
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=theme.FONT_SIZE_SM),
            text_color=theme.TEXT_MUTED,
        )
        self._progress_label.grid(row=1, column=0, sticky="w",
                                   padx=theme.SP_4, pady=(0, theme.SP_3))

        btn_row = ctk.CTkFrame(action, fg_color="transparent")
        btn_row.grid(row=1, column=1, sticky="e", padx=theme.SP_4, pady=(0, theme.SP_3))

        self._stop_btn = ctk.CTkButton(
            btn_row, text="Stop", width=88,
            fg_color=theme.BTN_DANGER_BG,
            hover_color=theme.BTN_DANGER_HOVER,
            border_color=theme.BTN_DANGER_BORDER, border_width=1,
            text_color=theme.BTN_DANGER_TEXT,
            state="disabled",
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=theme.FONT_SIZE_BASE),
            corner_radius=theme.RADIUS_SM,
            command=self._stop_batch,
        )
        self._stop_btn.pack(side="left", padx=(0, theme.SP_3))

        self._start_btn = ctk.CTkButton(
            btn_row, text="▶   Start Batch", width=152, height=36,
            fg_color=theme.BTN_PRIMARY_BG,
            hover_color=theme.BTN_PRIMARY_HOVER,
            text_color=theme.BTN_PRIMARY_TEXT,
            state="disabled",
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=theme.FONT_SIZE_BASE, weight="bold"),
            corner_radius=theme.RADIUS_SM,
            command=self._start_batch,
        )
        self._start_btn.pack(side="left")

    # ── Hint handling ─────────────────────────────────────────────────────────
    def _clear_hint(self, _e):
        if self._has_hint:
            self._prompt_box.delete("1.0", "end")
            self._prompt_box.configure(text_color=theme.TEXT_PRIMARY)
            self._has_hint = False

    def _restore_hint(self, _e):
        if not self._prompt_box.get("1.0", "end").strip():
            self._prompt_box.insert("1.0", HINT)
            self._prompt_box.configure(text_color=theme.TEXT_MUTED)
            self._has_hint = True

    def _update_count(self):
        if self._has_hint:
            self._count_label.configure(text="0 prompts", text_color=theme.TEXT_MUTED)
            return
        n = len(parse_prompts(self._prompt_box.get("1.0", "end")))
        self._count_label.configure(
            text=f"{n} prompt{'s' if n != 1 else ''}",
            text_color=theme.ACCENT if n > 0 else theme.TEXT_MUTED,
        )

    # ── Actions ───────────────────────────────────────────────────────────────
    def _browse_out(self):
        folder = filedialog.askdirectory(title="Select output folder")
        if folder:
            self._out_var.set(folder)
            self.app.config["last_output_dir"] = folder
            self.app.save_settings()

    def _open_browser(self):
        self._open_btn.configure(state="disabled", text="Opening…")
        self.app.set_status("Opening Google Flow in browser…")

        def launch():
            self._browser = BrowserWorker()
            ok = self._browser.open_flow()
            if ok:
                self.app.emit("status", "Log in → open a project in Flow → then click  ✓  I'm Logged In")
                self.after(0, self._on_browser_open)
            else:
                err = self._browser._error or "Unknown error"
                self.app.emit("status", f"⚠ Browser failed: {err[:60]}")
                self._browser = None
                self.after(0, self._on_browser_error)

        threading.Thread(target=launch, daemon=True).start()

    def _on_browser_open(self):
        self._open_btn.configure(state="normal", text="Open Google Flow")
        self._login_btn.configure(
            state="normal",
            text_color=theme.SUCCESS,
            border_color=theme.SUCCESS_BORDER,
        )

    def _on_browser_error(self):
        self._open_btn.configure(state="normal", text="Open Google Flow")

    def _confirm_login(self):
        self._login_btn.configure(
            state="disabled",
            text="✓  Logged In",
            fg_color=theme.BTN_SUCCESS_BG,
            hover_color=theme.BTN_SUCCESS_HOVER,
            text_color=theme.BTN_SUCCESS_TEXT,
            border_width=0,
        )
        self._start_btn.configure(state="normal")
        self.app.set_status("Ready — add prompts and click  ▶  Start Batch")

    def _start_batch(self):
        prompts = [] if self._has_hint else parse_prompts(self._prompt_box.get("1.0", "end"))
        if not prompts:
            self.app.set_status("⚠  No prompts — separate each block with a blank line")
            return
        out_dir = self._out_var.get().strip()
        if not out_dir:
            self.app.set_status("⚠  Select an output folder first")
            return
        if not self._browser:
            self.app.set_status("⚠  Open Google Flow and log in first")
            return

        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        self._running = True
        self._start_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        self._progress_bar.set(0)
        self._progress_label.configure(text=f"0 / {len(prompts)}")
        self.app.set_status(f"Generating {len(prompts)} images…")

        self.app.config["last_output_dir"] = str(out_path)
        self.app.save_settings()

        threading.Thread(
            target=self._browser.run_batch,
            args=(prompts, out_path, self.app.emit, lambda: self._running),
            daemon=True,
        ).start()

    def _stop_batch(self):
        self._running = False
        self._stop_btn.configure(state="disabled")
        self.app.set_status("Stopping after current image…")

    # ── Callbacks ─────────────────────────────────────────────────────────────
    def on_progress(self, current: int, total: int):
        self._progress_bar.set(current / total)
        self._progress_label.configure(text=f"{current} of {total} images generated")

    def on_batch_done(self, image_paths: list):
        self._running = False
        self._start_btn.configure(state="normal")
        self._stop_btn.configure(state="disabled")
        self._progress_bar.set(1.0)
        self._progress_label.configure(
            text=f"✓  {len(image_paths)} images saved",
            text_color=theme.SUCCESS,
        )
        self.app.set_status(f"Done — {len(image_paths)} images generated")
        self.app.video_tab.set_images_folder(self.app.config.get("last_output_dir", ""))
        self.app.tabs.set("②  Gallery")

    def on_batch_error(self, msg: str):
        self._running = False
        self._start_btn.configure(state="normal")
        self._stop_btn.configure(state="disabled")
        self._progress_label.configure(
            text=f"Error — {msg[:60]}",
            text_color=theme.DANGER,
        )
        self.app.set_status(f"Error: {msg}")
