# FactFlow (MCIE) — How to Run This Project

This guide assumes you are starting from **zero** on a fresh Windows machine —
nothing installed, nothing configured. Follow it top to bottom, in order,
don't skip steps.

This project now lives on GitHub:
**https://github.com/TheMarchantia/FactFlow-MCIE**

This guide is split into two parts:
- **Part 1** — get the project running on your machine (one-time setup).
- **Part 2** — the day-to-day git workflow for working on it as a team.

If you get stuck anywhere, stop and ask in the group chat rather than
guessing — most setup problems are a one-line fix once someone sees the
exact error message. Copy the **full** error text when you ask.

---

# PART 1 — Getting the project running

## 0. What you need installed before touching the project

| Tool | Version | Why |
|---|---|---|
| Git | any recent version | To download (clone) the project from GitHub and to push your changes back. |
| Python | **3.11.9 specifically** | The backend's ML dependencies (PaddleOCR, PaddlePaddle, spaCy) are most reliably supported on 3.11. Newer versions (3.12/3.13) can lack prebuilt wheels for some of these and cause install failures. |
| FFmpeg | any recent version | The preprocessing pipeline shells out to the `ffmpeg`/`ffprobe` command-line binaries directly (not a Python wrapper) to extract audio and keyframes from uploaded clips. Without it on your PATH, every clip upload fails immediately. |
| A Gemini API key | — | The reasoning stage calls Google's Gemini API. Everyone should get **their own personal key** (it's free to create) — see Step 6. Without a key, every clip still runs, it just always comes back `INCONCLUSIVE` instead of a real verdict. |
| Whisper.cpp (`whisper-cli`) + a ggml model | optional | Enables real speech-to-text on the clip's audio. If you skip this, the pipeline still runs fine — it just falls back to OCR-only (on-screen text) with no speech transcript. See Step 7. |
| PaddleOCR | nothing to install manually | Already included via `pip install -r requirements.txt` in Step 5. It downloads its own model files (~10-15MB) automatically the **first time** you actually process a clip — see Step 8, this trips people up if they're offline on their first test. |
| Android Studio | current stable | To run the Android client. |

---

## 1. Install Git

1. Go to **git-scm.com/download/win** — the download should start
   automatically for 64-bit Windows.
2. Run the installer. Every screen has a default option — just click
   **Next** through all of them, then **Install**.
3. Verify it worked — open a **new** Command Prompt window and run:
   ```
   git --version
   ```
   It should print something like `git version 2.xx.x`, not "not
   recognized".
4. One-time identity setup — git needs to know who's making commits. Run
   these two, with your own name and the email tied to your GitHub account:
   ```
   git config --global user.name "Your Name"
   git config --global user.email "your.email@example.com"
   ```
   You only ever do this once per machine.

---

## 2. Install Python 3.11.9

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

## 3. Install FFmpeg

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

## 4. Get the project (clone it from GitHub)

Everyone needs to be added as a **collaborator** on the GitHub repo first
(ask Shreyas if you haven't gotten an invite — check your email/GitHub
notifications and accept it).

1. Pick a simple folder to keep it in, e.g. directly under your user folder
   — **avoid** OneDrive-synced folders like Desktop if yours is OneDrive-backed,
   it can cause weird sync/permission errors with git. `C:\Dev\` is a good,
   simple choice.
2. Open Command Prompt and run:
   ```
   cd C:\Dev
   git clone https://github.com/TheMarchantia/FactFlow-MCIE.git
   ```
   (If `C:\Dev` doesn't exist yet, make it first: `mkdir C:\Dev`.)
3. This creates `C:\Dev\FactFlow-MCIE` with everything inside it:
   ```
   FactFlow-MCIE\
     backend\
     android\
     README.md
     HOW_TO_RUN.md
     .gitignore
   ```

From here on, this guide assumes your project folder is
`C:\Dev\FactFlow-MCIE` — swap in your actual path if it's different.

---

## 5. Backend setup

Open Command Prompt (not PowerShell — some steps below are simpler in cmd)
and navigate into the backend folder:
```
cd C:\Dev\FactFlow-MCIE\backend
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

**Install dependencies (this includes PaddleOCR, PaddlePaddle, spaCy, and
everything else the backend needs):**
```
pip install -r requirements.txt
```
This will take a few minutes — `paddlepaddle` alone is roughly 100MB. This
step only needs to be done once per machine; see Part 1, Step 10 about not
needing to repeat it every time.

**Download the spaCy language model** (used by the explicit claim detector
and entity extraction — the `pip install` above only installs the spaCy
library, not this model; if it's missing, both modules fall back to a
lexical-only path rather than crashing):
```
python -m spacy download en_core_web_sm
```

---

## 6. Get your own Gemini API key

The reasoning stage calls Google's Gemini API directly (with search
grounding) to produce the actual verdict.

**Each of you should generate your own personal key** — don't share one
key between all three of you, and never send your key to anyone else or
paste it into a file that gets committed to git (more on that in Part 2).

1. Go to **aistudio.google.com/apikey** and sign in with a Google account,
   then create a key. It's free to create and use within a generous free
   quota.
2. Set it as an environment variable **before** starting the backend, in
   the same Command Prompt window you'll run the server from:
   ```
   set GEMINI_API_KEY=your-key-here
   ```
3. Optional — override the model (defaults to `gemini-3.6-flash`, no need
   to touch this unless told to):
   ```
   set FACTFLOW_GEMINI_MODEL=gemini-3.6-flash
   ```

**If you skip this:** the backend does not error out. Every clip will run
the full pipeline and complete successfully, but the verdict will always
come back `INCONCLUSIVE` (this is a deliberate fallback, logged as a
warning, not a fabricated result) — so you can still test everything else
(the Android app, the upload flow, the popup) without a key, you just
won't see a real `TRUE`/`FALSE`/`MISLEADING` verdict.

**To avoid retyping this every session**, you can set it permanently
instead of using `set`:
- Press the Windows key, search **"Environment Variables"**, open **"Edit
  the system environment variables"** → **Environment Variables**.
- Under **User variables** (top box, not System variables), click **New**.
- Variable name: `GEMINI_API_KEY`, Variable value: your key.
- Click OK on everything. Open a **new** Command Prompt window for it to
  take effect.

---

## 7. (Optional) Install Whisper.cpp for real speech transcription

Speech-to-text on the clip's audio track is real (via Whisper.cpp), but
it's optional — without it, the pipeline just skips straight to OCR-only
(on-screen text) with no speech transcript, rather than failing the clip.
Skip this step entirely if you just want to get the project running first
and add it later.

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
   permanent-Environment-Variables options as Step 6):
   ```
   set FACTFLOW_WHISPER_BIN=C:\whisper\whisper-cli.exe
   set FACTFLOW_WHISPER_MODEL=C:\whisper\ggml-base.en.bin
   ```

If either variable is unset, or points somewhere invalid, the backend logs
a warning and continues without a transcript — it does not fail the clip.

---

## 8. PaddleOCR — nothing to configure, but read this once

Unlike Gemini and Whisper, **there is no key or path to set up for
PaddleOCR.** It's already installed by `pip install -r requirements.txt`
in Step 5, and it downloads its own detection/recognition model files
automatically — but only the **first time it actually runs**, i.e. the
first time you upload and process a real clip through the app, not when
you start the server.

What this means in practice:
- The **first** clip you ever test will take noticeably longer and needs
  **working internet access** — it's downloading ~10-15MB of model weights
  from `paddleocr.bj.bcebos.com` in the background.
- If that first clip fails, check your internet connection first — the
  error message will mention PaddleOCR or model download failures.
- Every clip after that is fast, since the models are cached locally.
- There is nothing to `set` and no file path to configure — this is purely
  "make sure you're online the first time you test."

---

## 9. Understand what happens when you upload a clip

Every uploaded clip runs the full pipeline end to end: FFmpeg → (optional
Whisper transcript) → PaddleOCR → MCIE claim detection/entity
extraction/confidence scoring → VPG query + keyframe selection → Gemini
reasoning call.

What that means in practice:
- **With `GEMINI_API_KEY` set (Step 6):** you get a real, grounded verdict
  (`TRUE` / `FALSE` / `MISLEADING` / `INCONCLUSIVE`) with a confidence
  score, summary, and sources.
- **Without it:** the clip still completes (status `completed`, not
  `failed`), but the verdict is always `INCONCLUSIVE`.
- **Without Whisper.cpp configured (Step 7):** claim detection runs on
  on-screen text only — the pipeline degrades gracefully rather than
  failing.
- **The one part of MCIE still a placeholder:** implied-claim detection
  (claims not explicitly stated) currently always returns an empty list.
  Explicit claim detection, entity extraction, confidence scoring, and
  verification-target selection are all real, rule-based logic — see the
  README's "current state" section for the full breakdown of what's real
  vs. still stubbed.

A clip will land in `"failed"` status if PaddleOCR itself errors out (most
commonly a first-run network issue reaching `paddleocr.bj.bcebos.com`, see
Step 8) — that failure is fatal, unlike the optional Whisper step.

---

## 10. Run the backend

From the `backend` folder, with `(venv)` active and `GEMINI_API_KEY` (and
optionally the Whisper variables) set in the **same terminal session** (or
set permanently, per Step 6):
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

## 11. Android Studio setup

1. Open Android Studio.
2. On the welcome screen, click **Open** (not "New Project" — that creates a
   brand new empty project and will not use any of the existing code).
3. Navigate to and select the `FactFlow-MCIE\android` folder specifically —
   the `android` folder itself, not its parent, and not any single file
   inside it.
4. Click OK and wait for Gradle sync to finish (progress bar at the bottom;
   can take several minutes the first time as it downloads dependencies).
5. If Android Studio complains about `local.properties` or an SDK path, this
   is expected on a new machine — it should auto-generate the file (this
   file is intentionally **not** part of the repo, since it's specific to
   each person's machine). If it doesn't auto-generate, go to **File →
   Project Structure → SDK Location** and point it at your installed
   Android SDK.

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

## 12. Testing the bubble + pipeline

With the backend running (Step 10) and the app running with the bubble
visible and permissions granted (Step 11):

1. **Tap the bubble once** → it turns red (recording state). This is a
   **real** screen recording (with mic audio) via `MediaProjection` — it
   captures whatever is actually on screen.
2. **Tap it again** → it turns amber (processing) and an upload starts.
   Watch the **Logcat** panel in Android Studio (filter by tag
   `BubbleService`) to see progress messages.
3. After the pipeline finishes, the bubble turns green/red/amber/grey
   depending on the verdict (`TRUE`/`FALSE`/`MISLEADING`/`INCONCLUSIVE`).
   If `GEMINI_API_KEY` wasn't set, expect `INCONCLUSIVE` every time (see
   Step 9) — that's expected, not a bug.
4. **Tap the bubble a third time** (while colored) → a popup appears showing
   the claim, verdict, confidence, summary, and sources.
5. Tap **Close** → bubble resets to grey, ready to test again.

You can also confirm data is really landing in the database by opening
`http://localhost:8000/docs` in a browser, expanding `GET /api/v1/history`,
clicking "Try it out" → "Execute".

---

# PART 2 — The git workflow (how we work on this together)

This is the part that matters once **more than one person** is editing the
project. Read this whole section once before making any changes, even
small ones.

## The one rule that matters most

**Nobody commits directly to the `main` branch.** `main` is the "always
works" copy — the one everyone clones and builds from. If you push broken
code straight to it, everyone else's project breaks the next time they
pull.

Instead, everyone works like this:
1. Create your own **branch** (a personal copy of the code, off of `main`)
   for whatever you're working on.
2. Make your changes and commit them **on your branch**.
3. Push your branch to GitHub.
4. Open a **Pull Request (PR)** — this is you asking "can this be merged
   into `main`?" — so someone else can look at the change before it lands.
5. Once it's approved and merged, everyone else picks it up next time they
   pull `main`.

This sounds like extra steps, but it means `main` never randomly breaks
because two people edited the same thing at the same time without knowing.

## Some git vocabulary, briefly

| Term | What it means |
|---|---|
| **Repository (repo)** | The whole project + its full history. This project's repo is `FactFlow-MCIE` on GitHub. |
| **Clone** | Downloading a full copy of the repo to your machine (Step 4, Part 1 — you only do this once). |
| **Branch** | A separate line of work, so your in-progress changes don't affect `main` until you're ready. |
| **Commit** | A saved snapshot of your changes, with a short message describing what changed. |
| **Push** | Uploading your commits from your machine to GitHub. |
| **Pull** | Downloading commits from GitHub that aren't on your machine yet. |
| **Pull Request (PR)** | A request on GitHub to merge your branch into `main`, so others can review it first. |
| **Merge** | Actually combining one branch's changes into another (usually done by clicking "Merge" on a PR, after review). |

## The daily workflow, step by step

**Every time you sit down to work on this project:**

**1. Make sure your local `main` is up to date first.**
```
cd C:\Dev\FactFlow-MCIE
git checkout main
git pull
```
This grabs anything the others have merged since you last checked. Do this
even if you're about to work on your own branch — you want to branch off
the latest `main`, not an old one.

**2. Create a new branch for what you're about to work on.**
Name it something short and descriptive — lowercase, hyphens instead of
spaces:
```
git checkout -b implied-claim-detection
```
(`git checkout -b <name>` creates the branch **and** switches you onto it
in one step.)

**3. Make your code changes as normal** — edit files in
`C:\Dev\FactFlow-MCIE` in whatever editor you're using (VS Code, Android
Studio, etc.), same as always.

**4. Check what you changed.**
```
git status
```
This lists every file you've modified/added/deleted. Read it — make sure
you're not about to commit something you didn't mean to (like a stray
`.env` file — see the warning box below).

**5. Stage and commit your changes.**
```
git add -A
git commit -m "Short description of what you did"
```
Write a real description — `"fix"` or `"update"` tells nobody anything six
weeks from now. `"Implement implied claim detection for date/location
mismatches"` does.

You can do steps 3–5 (edit, check, commit) as many times as you like while
working — lots of small commits are better than one giant one.

**6. Push your branch to GitHub.**
```
git push -u origin implied-claim-detection
```
(The `-u origin implied-claim-detection` part is only needed the **first**
time you push this particular branch — after that, plain `git push` works
for that branch.)

**7. Open a Pull Request on GitHub.**
- Go to the repo page — GitHub usually shows a yellow banner right after
  your push saying *"implied-claim-detection had recent pushes"* with a
  **Compare & pull request** button. Click it.
- If you don't see the banner, go to the **Pull requests** tab → **New pull
  request** → pick your branch.
- Add a short title/description of what the change does, then **Create
  pull request**.
- Let the others know in the group chat so someone actually looks at it.

**8. After it's merged (on GitHub, someone clicks "Merge pull request"):**
Switch back to `main` locally and pull the merged change in, then clean up
your old branch:
```
git checkout main
git pull
git branch -d implied-claim-detection
```

That's the full loop. Repeat from Step 1 for your next piece of work.

## If `git pull` says there's a conflict

This means someone else changed the same lines of a file you also changed,
and git can't automatically decide which version to keep. Don't panic and
don't just start deleting things:
1. Run `git status` — it'll list which file(s) have a conflict.
2. Open that file — git marks the conflicting section with `<<<<<<<`,
   `=======`, and `>>>>>>>` lines showing both versions.
3. Edit the file by hand to keep what should actually be there (removing
   the `<<<<<<<`/`=======`/`>>>>>>>` markers themselves).
4. `git add` the fixed file, then `git commit` to finish the merge.

If this looks confusing the first time it happens, that's normal — post a
screenshot in the group chat rather than guessing, it's much faster to
resolve with a second pair of eyes.

## ⚠️ Never commit secrets

Never put a real API key directly into a file that's part of the repo
(e.g. never hardcode `GEMINI_API_KEY` inside a `.py` file, and never create
a `backend\.env` file with a real key in it and then `git add` it). Always
set it as an environment variable per Step 6 in Part 1. The project's
`.gitignore` already excludes `backend/.env` as a safety net, but the
`set`/system-variable approach means there's no file containing your key
sitting in the folder at all.

Before running `git add -A`, glance at `git status` — if you ever see a
file you don't recognize as something you intentionally created (like an
`.env`), stop and ask before committing.

## Quick command cheat-sheet

```
git status                          — what have I changed?
git checkout main                   — switch to the main branch
git pull                            — get the latest changes from GitHub
git checkout -b my-branch-name      — create + switch to a new branch
git add -A                          — stage all your changes
git commit -m "message"             — save a snapshot with a message
git push -u origin my-branch-name   — push a new branch the first time
git push                            — push again after the first time
git branch -d my-branch-name        — delete a branch you're done with
git log --oneline -10                — see the last 10 commits, briefly
```

---

# Quick reference — what to repeat, and when

**One-time per machine** (Part 1, Steps 1–5, and Step 7 if you're using
Whisper): installing Git, Python, FFmpeg, cloning the repo, creating the
venv, `pip install -r requirements.txt`, downloading the spaCy model, and
downloading Whisper.cpp + its model.

**Every time you sit down to code** (start of your git workflow, Part 2):
```
cd C:\Dev\FactFlow-MCIE
git checkout main
git pull
git checkout -b your-new-branch     (or `git checkout your-existing-branch`)
```

**Every time you want to run the backend:**
```
cd C:\Dev\FactFlow-MCIE\backend
venv\Scripts\activate
set GEMINI_API_KEY=your-key-here                        (skip if set permanently)
set FACTFLOW_WHISPER_BIN=C:\whisper\whisper-cli.exe      (optional)
set FACTFLOW_WHISPER_MODEL=C:\whisper\ggml-base.en.bin   (optional)
uvicorn app.main:app --reload --host 0.0.0.0
```
...plus opening the `android` folder in Android Studio (it remembers the
project after the first open — pick it from Recent Projects).

**Only re-run `pip install -r requirements.txt`** if `requirements.txt`
itself changes (someone adds a new dependency and it shows up after your
`git pull`), or if you delete your `venv` folder.
