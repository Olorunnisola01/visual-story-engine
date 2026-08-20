"""
Deepgram transcription + context-aware segment splitting.

Splitting strategy:
  1. Detect natural pause points (gaps >= 0.25s between words)
  2. Snap each target split to the nearest pause — cuts feel natural
  3. If image prompts are provided, micro-nudge boundaries (±5 words)
     so each segment's spoken words overlap maximally with its prompt's keywords.
  4. Progressive order is always preserved: segment k starts after segment k-1.
"""

import re
import mimetypes
from pathlib import Path
import httpx


# ── Deepgram REST call ──────────────────────────────────────────────────────

def transcribe_audio(audio_path: Path, api_key: str) -> list[dict]:
    """Return word-level timestamps from Deepgram. Each: {word, start, end}."""
    audio_path = Path(audio_path)
    mime, _ = mimetypes.guess_type(str(audio_path))
    if not mime:
        mime = "audio/mpeg"

    url = "https://api.deepgram.com/v1/listen?model=nova-2&smart_format=true&words=true"
    headers = {"Authorization": f"Token {api_key}", "Content-Type": mime}

    with open(audio_path, "rb") as f:
        audio_bytes = f.read()

    with httpx.Client(timeout=120.0) as client:
        response = client.post(url, headers=headers, content=audio_bytes)

    response.raise_for_status()
    data = response.json()

    words_raw = data["results"]["channels"][0]["alternatives"][0]["words"]
    return [
        {"word": w["word"], "start": float(w["start"]), "end": float(w["end"])}
        for w in words_raw
        if w.get("start") is not None and w.get("end") is not None
    ]


# ── Keyword helpers ──────────────────────────────────────────────────────────

_STOPWORDS = frozenset({
    "a", "an", "the", "in", "on", "at", "of", "to", "and", "or",
    "is", "are", "was", "were", "be", "been", "being", "have", "has",
    "had", "do", "does", "did", "will", "would", "could", "should",
    "may", "might", "can", "for", "with", "by", "from", "this", "that",
    "there", "here", "what", "when", "where", "which", "who", "how",
    "i", "me", "my", "you", "your", "he", "she", "it", "we", "they",
    "their", "our", "its", "not", "no", "so", "as", "up", "out", "s",
    "also", "then", "just", "very", "now", "well", "more", "most",
})


def _keywords(text: str) -> frozenset[str]:
    tokens = re.findall(r'\b[a-z]+\b', text.lower())
    return frozenset(t for t in tokens if t not in _STOPWORDS and len(t) > 2)


# ── Core split logic ─────────────────────────────────────────────────────────

def split_words_into_segments(
    words: list[dict],
    n: int,
    prompts: list[str] | None = None,
) -> list[dict]:
    """
    Split word-level transcript into n segments with context-aware timing.

    - Natural pause detection: boundaries snap to silence gaps (>= 0.25 s)
    - Keyword matching: if prompts supplied, nudges each boundary ±5 words
      so each segment's spoken content best matches its image prompt
    - Monotone guarantee: segments are always in chronological order
    """
    if not words:
        raise ValueError("Deepgram returned no words — check audio quality and API key.")
    if n <= 0:
        raise ValueError("Need at least one image/prompt.")
    if n == 1:
        return [{"start": words[0]["start"], "end": words[-1]["end"],
                 "duration": max(0.5, words[-1]["end"] - words[0]["start"])}]

    total_words = len(words)

    # ── Step 1: locate natural pause indices ────────────────────────────────
    PAUSE_SECS = 0.25
    pause_set = set()  # word indices where a pause follows
    for i in range(total_words - 1):
        if words[i + 1]["start"] - words[i]["end"] >= PAUSE_SECS:
            pause_set.add(i)

    # ── Step 2: pick n-1 split points near ideal time-based positions ───────
    allowance = max(3, total_words // max(n * 3, 1))  # snap window per split
    splits = []
    for k in range(1, n):
        target = int(total_words * k / n)
        # Find the closest pause within the allowance window
        best_pause = None
        best_dist = float("inf")
        for p in pause_set:
            d = abs(p - target)
            if d <= allowance and d < best_dist:
                best_dist = d
                best_pause = p
        splits.append(best_pause if best_pause is not None else target)

    # ── Step 3: keyword-guided micro-adjustment ──────────────────────────────
    if prompts and len(prompts) == n:
        splits = _keyword_refine(words, splits, prompts)

    # ── Step 4: enforce strict monotone ordering ─────────────────────────────
    splits = _monotone(splits, total_words, n)

    # ── Step 5: build segment dicts from split indices ───────────────────────
    boundaries = [0] + [s + 1 for s in splits] + [total_words]
    segments: list[dict] = []
    for i in range(n):
        chunk = words[boundaries[i]: boundaries[i + 1]]
        if not chunk:
            prev = segments[-1] if segments else {"end": 0.0, "duration": 1.0}
            segments.append({
                "start": prev["end"],
                "end":   prev["end"] + prev["duration"],
                "duration": prev["duration"],
            })
        else:
            start = chunk[0]["start"]
            end   = chunk[-1]["end"]
            segments.append({"start": start, "end": end,
                              "duration": max(0.5, end - start)})

    return segments


def _keyword_refine(
    words: list[dict],
    splits: list[int],
    prompts: list[str],
) -> list[int]:
    """
    For each split boundary, search ±NUDGE words and pick the position that
    maximises keyword overlap between neighbouring segments and their prompts.
    """
    NUDGE = 5
    WINDOW = 12  # words on each side of a boundary to sample for scoring
    n = len(prompts)
    kws = [_keywords(p) for p in prompts]

    improved = list(splits)
    for idx, split in enumerate(splits):
        left_kw  = kws[idx]       # prompt for the segment ending here
        right_kw = kws[idx + 1]   # prompt for the segment starting here

        best_score = -1
        best_pos   = split

        lo = max(0, split - NUDGE)
        hi = min(len(words) - 2, split + NUDGE)

        for pos in range(lo, hi + 1):
            # Sample the tail of the left segment and head of the right segment
            left_words  = {words[j]["word"].lower()
                           for j in range(max(0, pos - WINDOW), pos + 1)}
            right_words = {words[j]["word"].lower()
                           for j in range(pos + 1, min(len(words), pos + 1 + WINDOW))}
            score = len(left_words & left_kw) + len(right_words & right_kw)
            if score > best_score:
                best_score = score
                best_pos   = pos

        improved[idx] = best_pos
    return improved


def _monotone(splits: list[int], total_words: int, n: int) -> list[int]:
    """Guarantee splits are strictly increasing and within [0, total_words-1]."""
    result = []
    prev = -1
    for i, s in enumerate(splits):
        s = max(prev + 1, min(s, total_words - (n - i)))
        result.append(s)
        prev = s
    return result


# ── Manual transcript ────────────────────────────────────────────────────────

def parse_manual_transcript(text: str, audio_duration: float) -> list[dict]:
    """
    Convert plain-text transcript to word-level dicts with proportional timestamps.
    No API needed — timing is estimated linearly by word position across audio_duration.
    """
    text = re.sub(r'\s+', ' ', text.strip())
    tokens = text.split()
    if not tokens:
        raise ValueError("Transcript is empty.")
    n = len(tokens)
    return [
        {"word": tok, "start": audio_duration * i / n, "end": audio_duration * (i + 1) / n}
        for i, tok in enumerate(tokens)
    ]


# ── Semantic alignment (Level 2 + 3) ────────────────────────────────────────

def _sentences_from_words(words: list[dict]) -> list[list[dict]]:
    """Group word dicts into sentences by terminal punctuation."""
    sentences: list[list[dict]] = []
    current: list[dict] = []
    for w in words:
        current.append(w)
        if re.search(r'[.!?…]$', w["word"].rstrip('"\'"”')):
            sentences.append(current)
            current = []
    if current:
        sentences.append(current)
    # Merge very short runs (< 3 words) into the following sentence
    merged: list[list[dict]] = []
    i = 0
    while i < len(sentences):
        if len(sentences[i]) < 3 and i + 1 < len(sentences):
            sentences[i + 1] = sentences[i] + sentences[i + 1]
            i += 1
        else:
            merged.append(sentences[i])
            i += 1
    return merged or [words]


# ── Timestamped prompts (most reliable — no transcription needed) ──────────

_TS_PATTERN = re.compile(
    r'(?:timestamp|time)\s*[:=]\s*'
    r'(\d{1,2}):(\d{2})(?::(\d{2}))?(?:[.,](\d{1,3}))?',
    re.IGNORECASE,
)


def parse_prompt_timestamp(prompt: str) -> float | None:
    """
    Extract an embedded timestamp from a prompt's own text, e.g.
    'Timestamp: 00:08:16' or 'Timestamp: 8:16.5'. Returns seconds, or None
    if no recognisable timestamp field is present.
    """
    m = _TS_PATTERN.search(prompt)
    if not m:
        return None
    a, b, c, frac = m.groups()
    if c is not None:
        h, mnt, s = int(a), int(b), int(c)
    else:
        h, mnt, s = 0, int(a), int(b)
    fractional = float("0." + frac) if frac else 0.0
    return h * 3600 + mnt * 60 + s + fractional


def extract_timestamp_via_llm(
    prompt_text: str,
    api_key: str,
    api_base: str,
    model: str,
) -> float | None:
    """
    Fallback for prompts whose timestamp doesn't match the standard
    'Timestamp: HH:MM:SS' pattern — asks the LLM to read whatever time
    value is written in the prompt and return it in seconds.
    """
    import json as _json
    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(
                f"{api_base.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://visual-story-engine",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content":
                            "Extract the timestamp mentioned in the text and return "
                            "ONLY JSON: {\"seconds\": <float>}. No explanation."},
                        {"role": "user", "content": prompt_text},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 40,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        m = re.search(r'\{.*\}', content, re.DOTALL)
        if not m:
            return None
        return float(_json.loads(m.group())["seconds"])
    except Exception:
        return None


def build_segments_from_prompt_timestamps(
    prompts: list[str],
    audio_duration: float,
    llm_key: str = "",
    llm_base: str = "",
    llm_model: str = "",
) -> list[dict] | None:
    """
    If every prompt embeds its own timestamp (regex first, LLM fallback per
    unparsed prompt if an LLM key is supplied), use those exact values as
    cut points directly — deterministic, no transcription or alignment
    guessing involved at all.

    Returns None if any prompt's timestamp still can't be determined.
    """
    times: list[float | None] = [parse_prompt_timestamp(p) for p in prompts]

    if llm_key:
        for i, t in enumerate(times):
            if t is None:
                times[i] = extract_timestamp_via_llm(prompts[i], llm_key, llm_base, llm_model)

    if any(t is None for t in times):
        return None

    times = [float(t) for t in times]  # type: ignore[arg-type]
    for i in range(1, len(times)):
        if times[i] < times[i - 1]:
            times[i] = times[i - 1]

    segments: list[dict] = []
    for i, t in enumerate(times):
        end = times[i + 1] if i + 1 < len(times) else audio_duration
        end = max(end, t + 0.1)
        segments.append({"start": t, "end": end, "duration": max(0.1, end - t)})
    return segments


def split_by_llm_alignment(
    words: list[dict],
    n: int,
    prompts: list[str],
    api_key: str,
    api_base: str,
    model: str,
) -> list[dict]:
    """
    Level 4: LLM-based semantic alignment via Groq or OpenRouter.

    Sends the transcript as readable sentences with timestamps and all image
    prompts to the LLM. The model determines — using full language understanding
    — the exact second where each image should appear. Handles metaphor,
    paraphrasing, and implicit topic shifts that embeddings miss.

    Falls back to split_by_semantic_alignment → split_words_into_segments on error.
    """
    import json as _json

    total = len(words)
    audio_end = words[-1]["end"]

    if n == 1:
        return [{"start": words[0]["start"], "end": audio_end,
                 "duration": max(0.5, audio_end - words[0]["start"])}]

    # Format transcript as sentences with timestamps — readable for the LLM
    sentence_groups = _sentences_from_words(words)
    sent_lines = []
    for sg in sentence_groups:
        t0 = sg[0]["start"]
        t1 = sg[-1]["end"]
        text = " ".join(w["word"] for w in sg)
        sent_lines.append(f"[{t0:.1f}s–{t1:.1f}s] {text}")
    transcript_block = "\n".join(sent_lines)
    prompts_block = "\n".join(f"Image {i+1}: \"{p}\"" for i, p in enumerate(prompts))

    system = (
        "You are a precise video timing assistant. "
        "Analyse a narration transcript and image prompts, then return JSON only — "
        "no explanation, no markdown, just the raw JSON object."
    )
    user = (
        f"TRANSCRIPT (audio ends at {audio_end:.1f}s):\n{transcript_block}\n\n"
        f"IMAGE PROMPTS ({n} images, shown in this order):\n{prompts_block}\n\n"
        f"Find the {n - 1} timestamps (in seconds) where the narration shifts to "
        f"describing each new image.\n"
        f"Rules:\n"
        f"- Image 1 always starts at 0s\n"
        f"- cuts[k] is the second where image k+2 first appears\n"
        f"- Cuts must be strictly increasing and within 0–{audio_end:.1f}\n"
        f"- Pick the moment the narrator *begins* speaking about what that next image shows\n\n"
        f'Return ONLY: {{"cuts": [t_for_img2, t_for_img3, ...]}}'
    )

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{api_base.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://visual-story-engine",  # OpenRouter requirement
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user",   "content": user},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 256,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()

        # Robust JSON extraction — strip markdown fences if present
        m = re.search(r'\{.*\}', content, re.DOTALL)
        if not m:
            raise ValueError(f"No JSON in response: {content[:300]}")
        data = _json.loads(m.group())
        cut_times = [float(c) for c in data["cuts"]]

        if len(cut_times) != n - 1:
            raise ValueError(f"Expected {n-1} cuts, got {len(cut_times)}")

        # Enforce strictly increasing, clamp to audio range
        cut_times = sorted(cut_times)
        clamped = []
        prev = 0.0
        for t in cut_times:
            t = max(prev + 0.1, min(t, audio_end - 0.1))
            clamped.append(t)
            prev = t
        cut_times = clamped

    except Exception:
        # Graceful degradation cascade
        try:
            return split_by_semantic_alignment(words, n, prompts)
        except Exception:
            return split_words_into_segments(words, n, prompts=prompts)

    # Map cut timestamps → nearest word index
    def _nearest_word(t: float) -> int:
        best, best_d = 0, float("inf")
        for i, w in enumerate(words):
            d = abs(w["start"] - t)
            if d < best_d:
                best_d, best = d, i
        return best

    cut_indices = [_nearest_word(t) for t in cut_times]

    # Build segments
    boundaries = [0] + cut_indices + [total]
    segments: list[dict] = []
    for i in range(n):
        si = boundaries[i]
        ei = min(boundaries[i + 1] - 1, total - 1)
        if si > ei:
            prev = segments[-1] if segments else {"end": 0.0, "duration": 1.0}
            segments.append({"start": prev["end"], "end": prev["end"] + prev["duration"],
                              "duration": prev["duration"]})
        else:
            s, e = words[si]["start"], words[ei]["end"]
            segments.append({"start": s, "end": e, "duration": max(0.5, e - s)})
    return segments


def split_by_semantic_alignment(
    words: list[dict],
    n: int,
    prompts: list[str],
) -> list[dict]:
    """
    Level 2+3 alignment: sentence embeddings + DP sequence alignment.

    - Segments transcript into sentences
    - Embeds every sentence and every image prompt with all-MiniLM-L6-v2
    - Finds the N-1 cut points (one per image boundary) that maximise total
      cosine similarity between each prompt and the sentences assigned to it,
      while keeping all cuts strictly in order (DP, O(M²·N))
    Falls back to keyword split_words_into_segments if sentence-transformers
    is not installed or fewer sentences than images.
    """
    import numpy as np

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return split_words_into_segments(words, n, prompts=prompts)

    if n == 1:
        return [{"start": words[0]["start"], "end": words[-1]["end"],
                 "duration": max(0.5, words[-1]["end"] - words[0]["start"])}]

    # ── 1. Sentence segmentation ────────────────────────────────────────────
    sentence_groups = _sentences_from_words(words)
    M = len(sentence_groups)
    if M < n:
        return split_words_into_segments(words, n, prompts=prompts)

    sentence_texts = [" ".join(w["word"] for w in sg) for sg in sentence_groups]

    # ── 2. Embed sentences and prompts ──────────────────────────────────────
    model = SentenceTransformer("all-MiniLM-L6-v2")
    prompt_embs = model.encode(prompts)    # [N, D]
    sent_embs   = model.encode(sentence_texts)  # [M, D]

    # Cosine similarity matrix [N, M]
    def _cos(a, b):
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))

    sim = np.array([[_cos(prompt_embs[i], sent_embs[j])
                     for j in range(M)] for i in range(n)])  # [N, M]

    # Prefix sums for fast mean-similarity queries: prefix[i][j] = sum sim[i][0..j-1]
    prefix = np.zeros((n, M + 1))
    for i in range(n):
        prefix[i, 1:] = np.cumsum(sim[i])

    def _seg_sim(pi: int, s: int, e: int) -> float:
        """Mean similarity of prompt pi over sentences s..e inclusive."""
        count = e - s + 1
        return float(prefix[pi, e + 1] - prefix[pi, s]) / count if count > 0 else -1.0

    # ── 3. DP: dp[i][j] = best total sim assigning prompts[0..i] to sentences[0..j] ──
    NEG_INF = -1e9
    dp   = np.full((n, M), NEG_INF)
    back = np.zeros((n, M), dtype=int)

    # Base: prompt 0 covers sentences 0..j (leave at least 1 sentence per remaining prompt)
    for j in range(M - (n - 1)):
        dp[0, j] = _seg_sim(0, 0, j)

    for i in range(1, n):
        lo_j = i
        hi_j = M - (n - 1 - i)
        for j in range(lo_j, hi_j):
            for k in range(i - 1, j):
                if dp[i - 1, k] == NEG_INF:
                    continue
                score = dp[i - 1, k] + _seg_sim(i, k + 1, j)
                if score > dp[i, j]:
                    dp[i, j] = score
                    back[i, j] = k

    # ── 4. Backtrack ────────────────────────────────────────────────────────
    # Last prompt must cover up to sentence M-1
    cut_sents: list[int] = []
    j = M - 1
    for i in range(n - 1, 0, -1):
        k = int(back[i, j])
        cut_sents.append(k + 1)   # image i starts at sentence k+1
        j = k
    cut_sents.reverse()

    # ── 5. Sentence indices → word indices → timestamps ──────────────────────
    word_start_of_sent: list[int] = []
    idx = 0
    for sg in sentence_groups:
        word_start_of_sent.append(idx)
        idx += len(sg)

    boundaries = [0] + [word_start_of_sent[cs] for cs in cut_sents] + [len(words)]

    segments: list[dict] = []
    for i in range(n):
        si = boundaries[i]
        ei = min(boundaries[i + 1] - 1, len(words) - 1)
        if si > ei:
            prev = segments[-1] if segments else {"end": 0.0, "duration": 1.0}
            segments.append({"start": prev["end"], "end": prev["end"] + prev["duration"],
                              "duration": prev["duration"]})
        else:
            s, e = words[si]["start"], words[ei]["end"]
            segments.append({"start": s, "end": e, "duration": max(0.5, e - s)})
    return segments
