# FactFlow (MCIE) — Multimodal Claim Intelligence Engine

Final-year project: a two-tap Android overlay bubble that lets someone
verify a claim made in a short-form video (Reels/Shorts-style) without
leaving the app they're scrolling in. Tap once to record a clip, tap again
to stop and send it for verification, tap a third time to see the verdict.

**Team:** Shreyas (backend + MCIE/VPG pipeline, Android bubble/capture) ·
Sahil Naik · Sarthak Mhatre
**Guide:** Ms. Nikita Saindane

---

## 1. How the pieces fit together

```
Android bubble (two-tap capture)
        │  screen + mic recording (MediaProjection)
        ▼
Backend upload endpoint  ──►  Preprocessing (FFmpeg + PaddleOCR + Whisper.cpp)
                                        │
                                        ▼
                              MCIE (claim detection, entity
                              extraction, confidence scoring)
                                        │
                                        ▼
                         VPG — Verification Package Generator
                         (query + keyframe + metadata assembly)
                                        │
                                        ▼
                         Gemini reasoning call (web-grounded)
                                        │
                                        ▼
                    Verdict stored + polled by the app + shown in popup
```

Two folders, run independently:
- `backend/` — FastAPI + SQLite. Does preprocessing, claim detection, and
  the reasoning call.
- `android/` — Kotlin/Compose. The floating bubble, screen capture, upload,
  polling, and the verdict popup / history screen.

**Full setup instructions are in [`HOW_TO_RUN.md`](./HOW_TO_RUN.md)** —
that's the file to follow to actually get this running on your machine,
from a completely fresh Windows install. This README is about *what state
the project is in* and *who's doing what next*, not step-by-step setup.

---

## 2. Current state — what's real vs. what's still a stub

**Fully working:**
- Backend API, database, upload handling
- FFmpeg audio extraction + keyframe extraction
- PaddleOCR on-screen text extraction
- MCIE: rule-based explicit claim detection (spaCy), entity extraction,
  the weighted confidence-scoring algorithm, verification-target selection
- VPG: query generation, keyframe selection, metadata assembly
- Gemini reasoning call — real API call with search grounding (needs a
  `GEMINI_API_KEY`; falls back to a logged `INCONCLUSIVE` verdict without
  one rather than erroring)
- Android: bubble overlay, drag, tap state machine, the full
  notification → overlay → mic → screen-capture permission chain, **real**
  `MediaProjection` screen+mic recording, upload, status polling, verdict
  popup, history screen
- Backend test suite covers preprocessing, OCR, and the MCIE/VPG pipeline
  stages (`backend/tests/`)

**Still a stub:**
- **Implied claim detection** (`app/mcie/implied_claim_detector.py`) always
  returns an empty list. Explicit (directly stated) claims are detected for
  real; claims that are implied rather than stated outright are not yet
  caught at all.

**Optional, degrades gracefully rather than blocking anything:**
- **Whisper.cpp speech transcription** — real when a `whisper-cli` binary +
  ggml model are configured; if not, the pipeline just proceeds OCR-only
  (no speech transcript) instead of failing the clip.

---

## 3. Known issues / rough edges

- No automated tests yet for `app/reasoning/gemini_client.py`'s actual API
  call path, or for anything under `app/vpg/` in isolation — only the
  combined pipeline test in `tests/test_pipeline.py`.
- `android/app/src/main/assets/sample_clip.mp4` (the old stand-in clip used
  before real screen capture existed) is still bundled in the repo and no
  longer referenced anywhere — safe to delete, just hasn't been cleaned up.
- Gemini reasoning quality hasn't been evaluated against a real set of
  claims/clips yet — prompt and verdict-parsing robustness (retries, edge
  cases in the JSON response) could use dedicated testing.
- Only tested on the emulator so far; the LAN-IP swap for a physical device
  (noted in `HOW_TO_RUN.md` Step 9) hasn't been verified end-to-end.
- No CI (GitHub Actions or similar) running the backend test suite yet.

---

## 4. Suggested task split

Shreyas has been carrying backend + MCIE/VPG + the Android capture/bubble
work solo up to this point. Rough split for the next phase — reassign
freely based on who wants what, this is just a starting point so nothing
falls through the cracks:

**Person A — Implied claim detection (MCIE)**
- Implement `app/mcie/implied_claim_detector.py` for real (currently
  returns `[]` unconditionally).
- Add test cases to `tests/test_pipeline.py` alongside the existing
  explicit-claim-detector tests.

**Person B — Reasoning quality + backend test coverage**
- Evaluate `app/reasoning/gemini_client.py` against a range of real clips
  once a `GEMINI_API_KEY` is available; tune the system prompt / VPG query
  wording in `app/vpg/query_generator.py` if verdicts are weak or
  inconsistent.
- Add tests for the Gemini client's JSON-parsing/retry logic and for the
  `app/vpg/` modules individually.

**Shreyas — Android polish + integration**
- Physical-device testing (LAN IP path), permission-chain edge cases
  (rotation, notification dismissal mid-recording), and general
  integration between backend changes and the app.
- Repo maintenance, README/HOW_TO_RUN upkeep, final report/demo prep.

Adjust this however makes sense once everyone's looked at the code —
the point is just to have a starting division on record.

---

## 5. Getting started

See **[`HOW_TO_RUN.md`](./HOW_TO_RUN.md)** for the full Windows setup guide
(Python, FFmpeg, Gemini API key, optional Whisper.cpp, Android Studio, and
how to actually test the bubble end-to-end).
