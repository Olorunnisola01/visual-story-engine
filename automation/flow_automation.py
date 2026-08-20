"""
Google Flow DOM automation.

Google Flow uses a project-based homepage. The automation handles:
  1. Detecting whether the page is the homepage or a project's generation view.
  2. Navigating into a project (or creating a new one) if on the homepage.
  3. Filling the prompt, triggering generation, waiting for a result, and
     downloading the image.

If Google updates the Flow UI, update the selector lists below.
"""

import time
from pathlib import Path
from playwright.sync_api import Page, TimeoutError as PWTimeout

# ── Selectors ─────────────────────────────────────────────────────────────────

# Textarea / contenteditable used to enter a generation prompt
PROMPT_SELECTORS = [
    "textarea[placeholder*='prompt' i]",
    "textarea[placeholder*='Describe' i]",
    "textarea[placeholder*='Write' i]",
    "textarea[placeholder*='Enter' i]",
    "textarea[aria-label*='prompt' i]",
    "[contenteditable][aria-label*='prompt' i]",
    "[contenteditable][placeholder*='prompt' i]",
    "textarea",
]

# Buttons that submit / generate
GENERATE_BUTTON_SELECTORS = [
    "button[aria-label*='Generate' i]",
    "button:has-text('Generate')",
    "button[aria-label*='Create' i]",
    "button:has-text('Create')",
    "[data-testid*='generate' i]",
    "button[aria-label*='Run' i]",
    # Arrow / send icon buttons (common in chat-style UIs)
    "button[aria-label*='Send' i]",
    "button[aria-label*='Submit' i]",
    "button[type='submit']",
]

# Newly generated image selectors (we wait for a *new* one to appear)
RESULT_IMAGE_SELECTORS = [
    "img[src*='generativelanguage.googleapis.com']",
    "img[src*='storage.googleapis.com']",
    "img[src*='lh3.googleusercontent.com']",
    "img[src*='medialab']",
    "[data-testid*='generated-image'] img",
    "[data-testid*='result'] img",
    "[class*='generated-image'] img",
    "[class*='generated'] img",
    "[class*='result'] img",
    "[class*='output'] img",
]

# Download button on the image card
DOWNLOAD_BUTTON_SELECTORS = [
    "button[aria-label*='download' i]",
    "button[aria-label*='save' i]",
    "button[title*='download' i]",
    "[data-testid*='download']",
    "a[download]",
]

# Button / link to navigate into a project from the homepage
NEW_PROJECT_SELECTORS = [
    "button:has-text('New project')",
    "a:has-text('New project')",
    "[aria-label*='New project' i]",
    "[data-testid*='new-project']",
    "button:has-text('Create project')",
    "button:has-text('Create')",
]

GENERATION_TIMEOUT_MS = 120_000  # 2 minutes per image


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_selector(page: Page, selectors: list[str]) -> str | None:
    for sel in selectors:
        try:
            if page.locator(sel).count() > 0:
                return sel
        except Exception:
            continue
    return None


def ensure_generation_view(page: Page) -> bool:
    """
    Make sure the page is showing the generation interface (prompt input is
    visible). If we're on the Flow homepage, navigate into an existing project
    or create a new one.

    Returns True if the generation view was reached, False if we couldn't
    navigate and the user should manually go to a project.
    """
    # Already in the generation view?
    if _find_selector(page, PROMPT_SELECTORS):
        return True

    # Try clicking "+ New project" on the homepage
    for sel in NEW_PROJECT_SELECTORS:
        try:
            if page.locator(sel).count() > 0:
                page.locator(sel).first.click()
                # Give the page 3 seconds to navigate / show the prompt input
                page.wait_for_timeout(3000)
                if _find_selector(page, PROMPT_SELECTORS):
                    return True
                break
        except Exception:
            continue

    # Try clicking the first existing project card
    try:
        # Project cards are typically links inside the project grid
        cards = page.locator("a[href*='flow']").all()
        for card in cards[:3]:
            href = card.get_attribute("href") or ""
            # Skip header links / navigation links; look for project-style paths
            if len(href) > 20 and "flow" in href:
                card.click()
                page.wait_for_timeout(3000)
                if _find_selector(page, PROMPT_SELECTORS):
                    return True
    except Exception:
        pass

    return bool(_find_selector(page, PROMPT_SELECTORS))


# ── Generation pipeline ───────────────────────────────────────────────────────

def fill_prompt(page: Page, prompt: str) -> bool:
    sel = _find_selector(page, PROMPT_SELECTORS)
    if not sel:
        raise RuntimeError(
            "Could not find the prompt input on Google Flow. "
            "Please navigate into a project's generation view first."
        )
    loc = page.locator(sel).first
    loc.click()
    loc.fill("")
    loc.type(prompt, delay=20)
    return True


def click_generate(page: Page) -> bool:
    sel = _find_selector(page, GENERATE_BUTTON_SELECTORS)
    if not sel:
        page.keyboard.press("Enter")
        return True
    page.locator(sel).first.click()
    return True


def wait_for_result(page: Page, previous_count: int) -> str | None:
    """
    Poll until a new generated image appears.
    Returns the image src URL or None on timeout.
    """
    deadline = time.time() + GENERATION_TIMEOUT_MS / 1000

    while time.time() < deadline:
        for sel in RESULT_IMAGE_SELECTORS:
            try:
                imgs = page.locator(sel).all()
                if len(imgs) > previous_count:
                    newest = imgs[-1]
                    src = newest.get_attribute("src")
                    if src:
                        return src
            except Exception:
                pass
        time.sleep(1.5)

    return None


def download_image(page: Page, img_url: str, output_path: Path) -> bool:
    """Download the generated image. Tries direct fetch first, then click-download."""
    try:
        response = page.context.request.get(img_url)
        if response.ok:
            output_path.write_bytes(response.body())
            return True
    except Exception as e:
        print(f"[download] fetch failed: {e}")

    # Fallback: click the download button and intercept the file save
    sel = _find_selector(page, DOWNLOAD_BUTTON_SELECTORS)
    if sel:
        try:
            with page.expect_download(timeout=15_000) as dl:
                page.locator(sel).last.click()
            dl.value.save_as(str(output_path))
            return True
        except Exception as e:
            print(f"[download] button failed: {e}")

    return False


def generate_one(page: Page, prompt: str, output_path: Path) -> bool:
    """
    Generate a single image from a prompt and save it to output_path.
    Returns True on success.
    """
    # Ensure we're in the generation interface, not on the homepage
    if not ensure_generation_view(page):
        raise RuntimeError(
            "Google Flow is showing the project homepage. "
            "Please click into a project (or create a new one), "
            "then click  ✓  I'm Logged In  in the app."
        )

    # Snapshot image count before generating
    previous_count = 0
    for sel in RESULT_IMAGE_SELECTORS:
        try:
            previous_count = max(previous_count, page.locator(sel).count())
        except Exception:
            pass

    fill_prompt(page, prompt)
    time.sleep(0.3)
    click_generate(page)

    img_url = wait_for_result(page, previous_count)
    if not img_url:
        return False

    return download_image(page, img_url, output_path)
