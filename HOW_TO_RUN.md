# FactFlow (MCIE) — How to Run This Project

This guide assumes you are starting from **zero** on a fresh Windows machine —
nothing installed, nothing configured. Follow it top to bottom in order.

**If you've run an older build of this project before:** the pipeline is no
longer stub-gated by an environment variable — it now always runs end to
end (MCIE → VPG → Gemini reasoning), and the Android bubble now does a real
screen + mic recording instead of uploading a bundled sample clip. See
Section 7 and Section 12 below if you only want to know what changed.

---

## 0. What you need installed before touching the project

| Tool | Version | Why |
|---|---|---|
| Python | **3.11.9 specifically** | The backend's ML dependencies (PaddleOCR, PaddlePaddle, spaCy) are most reliably supported on 3.11. Newer versions (3.12/3.13) can lack prebuilt wheels for some of these and cause install failures. |
| FFmpeg | any recent version | The preprocessing pipeline shells out to the `ffmpeg`/`ffprobe` command-line binaries directly (not a Python wrapper) to extract audio and keyframes from uploaded clips. Without it on your PATH, every clip upload fails immediately. |
| A Gemini API key | — | The reasoning stage now makes a real call to Google's Gemini API. Without a key, every clip completes with an `INCONCLUSIVE` verdict instead of erroring — see Section 5. |
| Whisper.cpp (`whisper-cli`) + a ggml model | optional | Enables real speech-to-text on the clip's audio. If you skip this, the pipeline still runs — it just falls back to OCR-only (on-screen text) with no speech transcript. See Section 6. |
| Android Studio | current stable | To run the Android client. |
| Git (optional) | any | Only needed if you're pulling this from a repo instead of a zip. |

---

## 1. Install Python 3.11.9

1. Go to **python.org/downloads/release/python-3119** and download the
   **Windows installer (64-bit)**.
2. Run the installer. On the **first screen**, check the box at the bottom:
   **"Add python.exe to PATH"**. This step is easy to miss and causes most
   "python is not recognized" errors later.
3. Click **Install Now** (default options are fine).
4. Verify it worked — open a **new** Command Prompt window (must be new, not
   one that was already open) and run:
   ```
   py -0
   ```
   You should see `-3.11` in the list. If Python was already installed
   before (a different version), this `py` launcher lets you target 3.11
   specifically without uninstalling anything else.

---

## 2. Install FFmpeg

Windows does not ship FFmpeg, and it isn't a `pip install` — it's a separate
program that needs to be on your system PATH.

1. Go to **gyan.dev/ffmpeg/builds** and download the **"release essentials"**
   build (a `.7z` or `.zip`).
2. Extract it somewhere permanent, e.g. `C:\ffmpeg`. After extracting, you
   should have a folder like `C:\ffmpeg\bin` containing `ffmpeg.exe` and
   `ffprobe.exe`.
3. Add it to PATH:
   - Press the Windows key, search **"Environment Variables"**, open
     **"Edit the system environment variables"**.
   - Click **Environment Variables**.
   - Under **System variables**, find and select **Path**, click **Edit**.
   - Click **New**, paste in `C:\ffmpeg\bin` (or wherever your `bin` folder
     actually is).
   - Click OK on every dialog to save.
4. Verify it worked — open a **new** Command Prompt window and run:
   ```
   ffmpeg -version
   ffprobe -version
   ```
   Both should print a version banner, not "not recognized as an internal or
   external command".

---

## 3. Unzip the project

Extract the project zip somewhere simple, e.g. `Desktop\MCIE\factflow`.
You should end up with two folders side by side:
```
factflow\
  backend\
  android\
```

---

## 4. Backend setup

Open Command Prompt (not PowerShell — some steps below are simpler in cmd)
and navigate into the backend folder:
```
cd Desktop\MCIE\factflow\backend
```

**Create the virtual environment, pinned to Python 3.11:**
```
py -3.11 -m venv venv
```

**Activate it:**
```
venv\Scripts\activate
```
Your prompt should now start with `(venv)`. Confirm the right Python version
is active:
```
python --version
```
This must print `Python 3.11.9` (or another 3.11.x). If it prints something
else, the venv wasn't created with `py -3.11` — delete the `venv` folder
(`rmdir /s /q venv`) and repeat the step above.

**Install dependencies:**
```
pip install -r requirements.txt
```
This will take a few minutes — `paddlepaddle` alone is roughly 100MB. This
step only needs to be done once; see the note at the bottom of this guide
about not needing to repeat it every time.

**Download the spaCy language model** (used by the explicit claim detector
and entity extraction — the install above only installs the spaCy library,
not this model; if it's missing, both modules fall back to a
lexical-only path rather than crashing):
```
python -m spacy download en_core_web_sm
```

---

## 5. Get a Gemini API key (for real verdicts)

The reasoning stage now calls Google's Gemini API directly (with search
grounding) instead of returning a hardcoded mock verdict.

1. Go to **aistudio.google.com/apikey** and create a key (a free Google
   account is enough to get started).
2. Set it as an environment variable **before** starting the backend:
   ```
   set GEMINI_API_KEY=your-key-here
   ```
   Like the FFmpeg PATH entry in Step 2, you can instead add
   `GEMINI_API_KEY` permanently via the same **Environment Variables**
   dialog so you don't have to `set` it every session — see Section 12.
3. Optional — override the model (defaults to `gemini-3.6-flash`):
   ```
   set FACTFLOW_GEMINI_MODEL=gemini-3.6-flash
   ```

**If you skip this:** the backend does not error out. Every clip will run
the full pipeline and complete successfully, but the verdict will always
come back `INCONCLUSIVE` (this is a deliberate fallback, logged as a
warning, not a fabricated result).

---

## 6. (Optional) Install Whisper.cpp for real speech transcription

Speech-to-text on the clip's audio track is now real (via Whisper.cpp), but
it's optional — without it, the pipeline just skips straight to OCR-only
(on-screen text) with no speech transcript, rather than failing the clip.

1. Go to **github.com/ggml-org/whisper.cpp/releases** and download the
   prebuilt Windows binary (look for a `whisper-bin-x64.zip`-style asset).
2. Extract it somewhere permanent, e.g. `C:\whisper`.
3. Download a model in ggml format from
   **huggingface.co/ggerganov/whisper.cpp** — `ggml-base.en.bin` (~148MB)
   is a good default — and save it into the same folder.
4. Note: the prebuilt binary needs the Microsoft Visual C++ Redistributable
   installed (`aka.ms/vs/17/release/vc_redist.x64.exe`) if it fails to
   launch.
5. Set two environment variables before starting the backend (same `set` /
   permanent-PATH-style options as before):
   ```
   set FACTFLOW_WHISPER_BIN=C:\whisper\whisper-cli.exe
   set FACTFLOW_WHISPER_MODEL=C:\whisper\ggml-base.en.bin
   ```

If either variable is unset, or points somewhere invalid, the backend logs
a warning and continues without a transcript — it does not fail the clip.

---

## 7. Understand what happens when you upload a clip

This changed from earlier builds, so it's worth reading even if you've run
this project before.

**There is no longer an environment-variable toggle that stops verification
after preprocessing.** Every uploaded clip now runs the full pipeline:
FFmpeg → (optional Whisper transcript) → PaddleOCR → MCIE claim
detection/entity extraction/confidence scoring → VPG query + keyframe
selection → Gemini reasoning call.

What that means in practice:
- **With `GEMINI_API_KEY` set (Section 5):** you get a real, grounded
  verdict (`TRUE` / `FALSE` / `MISLEADING` / `INCONCLUSIVE`) with a
  confidence score, summary, and sources.
- **Without it:** the clip still completes (status `completed`, not
  `failed`), but the verdict is always `INCONCLUSIVE`.
- **Without Whisper.cpp configured (Section 6):** claim detection runs on
  on-screen text only — the pipeline degrades gracefully rather than
  failing.
- **The one part of MCIE still a placeholder:** implied-claim detection
  (claims not explicitly stated) currently always returns an empty list.
  Explicit claim detection, entity extraction, confidence scoring, and
  verification-target selection are all real, rule-based logic now — see
  Section 11 for the full breakdown.

A clip will still land in `"failed"` status if PaddleOCR itself errors out
(e.g. it can't reach `paddleocr.bj.bcebos.com` to download its model
weights on first use) — that failure is still fatal, unlike the optional
Whisper step.

---

## 8. Run the backend

From the `backend` folder, with `(venv)` active and `GEMINI_API_KEY` (and
optionally the Whisper variables) set in the **same terminal session**:
```
uvicorn app.main:app --reload --host 0.0.0.0
```
You should see `Application startup complete.` with no errors.

**Verify it's actually working** — open a browser and go to:
```
http://localhost:8000/docs
```
You should see the FastAPI interactive docs page. (Do **not** try to open
`http://0.0.0.0:8000` directly in a browser — `0.0.0.0` means "listen on
every network interface," it's not a real address to connect *to*. Always
use `localhost` or `127.0.0.1` in the browser.)

Leave this terminal window open and running while you use the Android app.

---

## 9. Android Studio setup

1. Open Android Studio.
2. On the welcome screen, click **Open** (not "New Project" — that creates a
   brand new empty project and will not use any of the existing code).
3. Navigate to and select the `factflow\android` folder specifically — the
   `android` folder itself, not its parent, and not any single file inside
   it.
4. Click OK and wait for Gradle sync to finish (progress bar at the bottom;
   can take several minutes the first time as it downloads dependencies).
5. If Android Studio complains about `local.properties` or an SDK path, this
   is expected on a new machine — it should auto-generate the file. If it
   doesn't, go to **File → Project Structure → SDK Location** and point it
   at your installed Android SDK.

**Run it:**
1. Pick an emulator from the device dropdown (create one via **Device
   Manager** if none exist yet — any recent phone profile, API 29+, works).
2. Click Run (the green triangle).
3. On first launch (Android 13+) you'll get a notifications permission
   prompt — accept it.
4. Tap **"Start Bubble"**. You'll now go through a short consent chain, in
   this order, each step only appearing if not already granted:
   - **Overlay permission** — Android takes you to a system settings screen;
     enable it and return to the app (you'll likely need to tap "Start
     Bubble" again).
   - **Microphone permission** — needed because the real screen recording
     captures mic audio alongside video.
   - **Screen-capture consent** — the system's "Start recording or casting"
     dialog. This is asked once per bubble session, not once per clip — it's
     reused for every recording until you stop and restart the bubble.
5. A circular bubble should appear floating on screen.

**Note on networking:** the app is already configured to talk to
`http://10.0.2.2:8000`, which is the special address an Android **emulator**
uses to reach your computer's own `localhost:8000`. This only works on the
emulator. If you switch to testing on a real physical phone later, you'll
need to change that URL in `FactFlowApp.kt` to your computer's actual LAN IP
address (e.g. `http://192.168.1.23:8000`), and both devices must be on the
same Wi-Fi network.

---

## 10. Testing the bubble + pipeline

With the backend running (Step 8) and the app running with the bubble
visible and permissions granted (Step 9):

1. **Tap the bubble once** → it turns red (recording state). This is now a
   **real** screen recording (with mic audio) via `MediaProjection` — it
   captures whatever is actually on screen, not a bundled sample clip.
2. **Tap it again** → it turns amber (processing) and an upload starts.
   Watch the **Logcat** panel in Android Studio (filter by tag
   `BubbleService`) to see progress messages.
3. After the pipeline finishes, the bubble turns green/red/amber/grey
   depending on the verdict (`TRUE`/`FALSE`/`MISLEADING`/`INCONCLUSIVE`).
   If `GEMINI_API_KEY` wasn't set, expect `INCONCLUSIVE` every time (see
   Section 7) — that's expected, not a bug.
4. **Tap the bubble a third time** (while colored) → a popup appears showing
   the claim, verdict, confidence, summary, and sources.
5. Tap **Close** → bubble resets to grey, ready to test again.

You can also confirm data is really landing in the database by opening
`http://localhost:8000/docs` in a browser, expanding `GET /api/v1/history`,
clicking "Try it out" → "Execute".

---

## 11. What is and isn't implemented right now (so nothing here surprises you)

**Real / working:**
- Backend API, database, upload handling
- FFmpeg-based audio extraction + keyframe extraction
- PaddleOCR on-screen text extraction
- Rule-based explicit claim detection (spaCy), entity extraction, and the
  weighted confidence-scoring algorithm
- Verification-target selection and VPG query/keyframe generation
- Gemini reasoning call — real API call with search grounding (requires
  `GEMINI_API_KEY`; falls back to `INCONCLUSIVE` without one)
- Android bubble overlay, drag, tap states — including the full
  notification/overlay/mic/screen-capture permission chain
- **Real `MediaProjection` screen + mic recording** — tapping the bubble
  now records the actual screen, not the bundled sample video
- Upload, status polling, popup, history endpoint

**Still stubbed (hardcoded/placeholder, not real):**
- Implied claim detection — always returns an empty list (explicit claim
  detection is real; only the "unstated claim" path is still a stub)

**Optional / graceful fallback rather than a hard requirement:**
- Whisper.cpp speech transcription — real when configured (Section 6);
  otherwise the pipeline silently continues OCR-only

---

## 12. Do you need to repeat any of this every time?

**No.** Steps 1–4 (installing Python, FFmpeg, creating the venv, installing
requirements) and Step 6's Whisper.cpp download are **one-time setup** per
machine. Every time you come back to work on the project after that, you
only need:

```
cd Desktop\MCIE\factflow\backend
venv\Scripts\activate
set GEMINI_API_KEY=your-key-here
set FACTFLOW_WHISPER_BIN=C:\whisper\whisper-cli.exe    (optional, see Step 6)
set FACTFLOW_WHISPER_MODEL=C:\whisper\ggml-base.en.bin (optional, see Step 6)
uvicorn app.main:app --reload --host 0.0.0.0
```

...plus opening the `android` folder in Android Studio (it remembers the
project, so after the first open you can usually just pick it from the
Recent Projects list).

As with FFmpeg in Step 2, you can avoid retyping `GEMINI_API_KEY` and the
Whisper variables every session by adding them permanently through the same
**Environment Variables** system dialog instead of `set`-ing them per
terminal.

You only need to run `pip install -r requirements.txt` again if the
`requirements.txt` file itself changes (a new package gets added later) or
if you delete the `venv` folder.
