# Software Bill of Materials — v1 (Phase 0)

Every component is open source or genuinely free: **cost is $0 for every
row**. Sizes are bundled-size estimates from the project plan and must be
re-pinned to exact versions + hashes at download time (Phase 0, step 0.4
licence audit). Licence flags: ✅ permissive/free · ⚠️ usable with the
stated condition.

## Status in the shipped build (full spec audit, 2026-11-26)

The table below is the full component inventory the plan considered.
What the shipped build actually contains, verified against
`pyproject.toml`, `mimforge.spec` and `src/`:

- **Bundled and used:** PySide6, `cryptography`, opencv-python-headless,
  faster-whisper (+ CTranslate2), MuJoCo, build123d/OCP, SQLite
  (stdlib), numpy and av (direct dependencies, see their row), and
  ONNX Runtime — a direct dependency since 2026-11-26: it runs the
  SAM 2.1 click tracker's ONNX graphs (and also arrives transitively
  via faster-whisper).
- **Tool-only (build machines, never bundled):** PyInstaller, Inno
  Setup, QNX SDP + QEMU.
- **Remote, $0:** Muse Spark via the owner's Worker (only when its
  address is configured; offline by default), Firebase (Firestore
  metadata over stdlib REST — **Auth IS integrated since
  2026-11-26**: an email/password sign-in surface in the shell, and
  sync reads/writes each signed-in user's own subtree
  `users/{uid}/sync/...` under per-user rules; the app is fully
  usable signed out, and a live account round-trip is proven).
- **Bundled since Stage 0 (2026-11-26)**: FFmpeg/ffprobe (BtbN
  `lgpl` shared build, pinned release + SHA-256, staged at
  packaging time by `setup/fetch_bundled_assets.py`), the SAM 2.1
  weights and the Whisper `base` model are INSIDE the app under
  `mimforge_resources/`, resolved through `mimforge.resources`;
  the Firebase web config ships as a generated package resource
  the same way. First use needs no download and no network; the
  SAM first-run download remains only as a repair path.
- **NOT in this build** (rows kept for the record, marked as such):
  MediaPipe and Piper are **not integrated** (no code, no models
  ship). RTMPose, Qwen2.5-Coder and Webots are optional and
  absent. There is no TTS in this build. Trajectory retargeting
  IS in this build (own code, `retarget.py`, added 2026-11-26).

| Component | Purpose | Licence | Cost | ~Size | Notes |
|---|---|---|---|---|---|
| PySide6 (Qt for Python) | Desktop shell: authoring UI, playback UI, generated control panels | LGPL-3 ⚠️ | $0 | ~120 MB | Ship Qt DLLs dynamically + include licence notices. (PyQt6 rejected: GPL/commercial.) **Pinned in this VM: 6.12.0 (2026-11-25).** |
| PyInstaller 6.x | Windows packaging | GPL-2 with bootloader exception ⚠️ | $0 | tool only | Bootloader exception means packaged apps are unaffected. **Pinned in this VM: 6.22.3 (2026-11-25).** Linux smoke build verified 2026-11-25 (onedir, 1.2 GB, app starts headless offscreen). |
| `cryptography` (Ed25519) | Sign & verify `.tmachine` packages | Apache-2.0/BSD ✅ | $0 | ~5 MB | **Pinned in this VM: 50.0.2 (2026-11-25).** Used instead of PyNaCl for the signing module (an earlier duplicate row naming PyNaCl was removed in the 2026-11-26 audit — PyNaCl is not shipped). No commercial code-signing certificate is needed for package signing (an Authenticode cert for the installer is a paid SmartScreen *convenience* only — owner decision, not a dependency). |
| Inno Setup | Windows installer | Free licence ✅ | $0 | tool only | — |
| FFmpeg (**LGPL build only**) | Video probe, audio extraction | LGPL-3 ⚠️ | $0 | ~100 MB installed (bin + shared libs) | **BUNDLED since Stage 0 (2026-11-26).** Pinned: FFmpeg-Builds release `autobuild-2026-11-26-12-56`, `lgpl` SHARED variant only (win64 zip SHA-256 `7c762769…`, linux64 tar SHA-256 `b818772f…`, verified by `setup/fetch_bundled_assets.py` on every fetch). Unmodified standalone executables invoked as child processes; `LGPL-3.0.txt` + a source-offer notice ship in the bundle (`mimforge_resources/licenses/`, plus the build's own LICENSE in `bin/`). **GPL builds are never used** (the product is proprietary; the LGPL build does everything needed — the app only decodes/probes, it never encodes H.264). |
| MediaPipe (Pose + Hand Landmarker) | Teacher body/hand trajectories, CPU, GPU-optional | Apache-2.0 ✅ | $0 | **NOT in this build** | Models: Lite 3 MB / Full 6 MB / Heavy 26 MB. Lean mode uses Lite/Full. (Ultralytics YOLO rejected: AGPL-3.0 or paid Enterprise. OpenPose rejected: non-commercial.) |
| RTMPose-m via rtmlib / ONNX *(optional, post-hackathon)* | Higher-accuracy pose option | Apache-2.0 ✅ | $0 | ~50 MB | Checkpoint licence to be re-checked on the exact file at download. Not in the hackathon slice. |
| ONNX Runtime | CPU/DirectML inference runtime | MIT ✅ | $0 | ~15 MB | Direct dependency since 2026-11-26: runs the SAM 2.1 click tracker. **Pinned in this VM: 1.32.0.** |
| SAM 2.1 (hiera-tiny, ONNX) | Click-to-track segmentation of apparatus/objects the colour tracker cannot separate | Apache-2.0 ✅ (code **and** checkpoints) | $0 | 130,129,714 B, **bundled since Stage 0** (first-run download kept as repair path only) | **Integrated 2026-11-26** (`src/mimforge/sam_tracker.py`). The exact files are the `cstr/sam2.1-hiera-tiny-ONNX` conversion of Meta's SAM 2.1 hiera-tiny checkpoint — a format conversion only, no weights retrained — published under Apache-2.0, the same licence as SAM 2 itself: `encoder.onnx` 109,473,919 B + `decoder.onnx` 20,655,795 B. Downloaded once on first use into the app's `models` folder, SHA-256 pinned in code, works offline afterwards. Approach: the image model runs per examined frame, each frame prompted with points sampled inside the previous mask (not the video-memory predictor). Measured on the proving clip (classroom footage whose moving mass the colour tracker cannot separate from the board at all): a mask in 100% of examined frames, but the chained prompt migrates off a small object hanging from a long thin structure, so the SAM track there is a found-object track, not a measurement — no period is recovered from it (see the progress log, 2026-11-26). (SAM 3 rejected: gated, bespoke non-OSI licence.) |
| faster-whisper (CTranslate2) + Whisper **base** (lean) / small | Offline narration transcription with timestamps | MIT ✅ (code + weights) | $0 | base ~150 MB, small ~500 MB | Lean mode defaults to **base**. **The base weights are BUNDLED since Stage 0** (`Systran/faster-whisper-base` at pinned revision `ebe41f70…`, staged by the packaging fetch step; hashes recorded in `bundled/manifest.json` at build time). (Cloud speech-to-text rejected: paid.) **Pinned in this VM: faster-whisper 1.2.1, ctranslate2 4.9.1, onnxruntime 1.32.0, av 13.1.0 (2026-11-25).** av is pinned: faster-whisper 1.2.1 passes `metadata_errors` to PyAV, which av 19.x removed (TypeError) and av 14.4.0 ships no cp312 wheel on this index (its sdist needs system FFmpeg dev libs). |
| opencv-python-headless | Frame ingest + colour-prompt object tracking (Phase 2.1) | Apache-2.0 ✅ | $0 | ~90 MB | Headless build: no GUI deps. **Pinned in this VM: 5.1.0.95 (2026-11-25).** |
| Piper TTS — *original rhasspy/piper release only* | Spoken narration on school PCs, offline | Engine MIT ⚠️ | $0 | **NOT in this build** | **⚠️ PER-VOICE LICENCE CAVEAT: Piper voice licences vary by voice. Pin the original MIT engine release (the active fork is GPL-3.0) and licence-check the exact bundled voice individually; record the voice + its licence here before shipping. Fallback if the audit fails: ship recorded teacher narration only — always available, zero risk.** |
| Muse Spark via owner's Cloudflare Worker | Advisory drafting only: step text, discrepancy explanations, draft code for review | $0 to developer (owner's free credits) | $0 | 0 (remote) | API key is a Worker secret, never in the app; app holds only the Worker URL. Every feature has an offline fallback. Never used for safety logic. |
| Qwen2.5-Coder-7B-Instruct GGUF via llama.cpp *(optional download, never required)* | Offline drafting on the dev laptop | Model Apache-2.0 ✅ (verify model card at download); llama.cpp MIT | $0 | ~4.5 GB (Q4) | Optional module only — excluded from the hackathon build and from lean mode. Template codegen is the primary path. |
| Demonstration ↔ machine comparison + trajectory retargeting (built in-house) | The discrepancy engine compares the recorded demonstration track against the simulated machine track; `retarget.py` maps the recorded path onto the machine's coordinate frame (reach-clamped, safety-cap time-warped, fidelity reported) for Simulate's trajectory replay and lesson replay tracks | Own code (Apache-2.0, this repo) ✅ | $0 | — | **Trajectory retargeting EXISTS in V1** (added 2026-11-26): deterministic kinematic mapping, not learned motion transfer. LeRobot/SmolVLA remain a post-V1 research track (they need robot episode datasets + GPU training). |
| Muse Spark double-checker (owner's Cloudflare Worker) | Advisory second opinion at five build steps (draft, verification, generated code, lesson, risk assessment): the app sends a structured summary of the step's own result and shows AGREE / FLAG; the local result is always the official one and the checker never touches the safety kernel | $0 to developer (owner's free credits) | $0 | 0 (remote) | **Wired and ready 2026-11-26** (`checker.py`): same `MIMFORGE_WORKER_URL` configuration as the drafting advisor, 5 s timeout, per-day cap of 50 calls stored locally, rail toggle + daily counter. **No endpoint exists for Mimforge yet** — the owner sets up the Worker secret himself later; until then every check reports NOT SET UP and every step proceeds locally. Fully tested against a fake transport. |
| MuJoCo 3.x | Machine simulation + discrepancy scoring | Apache-2.0 ✅ | $0 | ~100 MB | The scoring engine. (NVIDIA Isaac Sim rejected: GPU-heavy, layered licensing.) **Pinned in this VM: 4.0.1 (2026-11-25).** |
| Webots R2025a *(optional)* | Visualisation/teaching simulator for schools | Apache-2.0 ✅ | $0 | — | Optional; MuJoCo remains the scoring engine. |
| build123d (OCCT kernel) | Parametric CAD → STEP/STL for platform library | Apache-2.0 ✅ | $0 | ~250 MB | (Fusion/SolidWorks rejected: paid. FreeCAD/LGPL is the GUI fallback for hand edits.) **Pinned in this VM: build123d 0.13.0, cadquery-ocp 8.0.1.1.0 (2026-11-25).** The underlying OCCT kernel is LGPL-2.1; it is a build-time tool only, and generated STEP/STL geometry is the app's own output. |
| numpy + av (PyAV) | Numeric core (tracking, fits) + media decode under faster-whisper | BSD-family ✅ | $0 | ~40 MB | Direct dependencies in `pyproject.toml`. av is pinned `==13.1.0` (see the faster-whisper row for why). |
| SQLite (Python stdlib) | Projects, templates, parts DB | Public domain ✅ | $0 | ~2 MB | Local source of truth, with project folders. |
| Firebase (Spark plan) — Auth + Firestore metadata | Email/password sign-in (Identity Toolkit REST, stdlib HTTP) + project *metadata* sync under each user's own subtree `users/{uid}/sync/...`; per-user Firestore rules (a user reads/writes only their own subtree) deployed 2026-11-26 | Free tier ✅ | $0 | 0 (remote) | **Storage is NOT used** (requires paid Blaze). Quotas: Firestore 1 GiB, 50k reads/day, 20k writes/day; Auth 50k MAU. Core workflows must pass with Firebase disabled and signed out. A live throwaway-account round-trip (create → write → read → delete) is proven in the test suite. |
| QNX SDP 8.0 + QEMU *(dev machine only, later phase)* | Cross-compile the generated C controller; run/test the QNX target | SDP free for **non-commercial** use ⚠️; QEMU GPL (tool only, not bundled) | $0 | SDP ~6.4 GB installed (not bundled) | Hackathon/education use fits the free licence. **Flag:** commercial deployment of QNX on sold machines would need a commercial QNX licence (owner decision D6). |
| WAEC syllabus PDFs + Chief Examiner reports | Template objectives, marking tolerances (reference only) | WAEC copyright ⚠️ | $0 | 0 | Reference/link only — **never redistributed or bundled**. Teacher-authored templates are the distributable asset. |

**Totals (measured 2026-11-26):** the Windows installer artifact is
~188 MB and the unpacked app folder ~290 MB. The pre-build estimate
(full engine ≈ 1.5–2.5 GB; lean ≈ 700–900 MB) assumed SAM and the
Whisper weights were bundled; neither is in this build (see the
status section above).

**Explicitly rejected on licence/cost grounds:** Ultralytics YOLO
(AGPL-3.0 / paid Enterprise), SAM 3 (gated bespoke licence), OpenPose
(non-commercial), PyQt6 (GPL/commercial), GPL FFmpeg builds, NVIDIA Isaac
Sim, cloud STT/TTS APIs, Llama Guard (gated Llama Community Licence, 12B —
and a content classifier, not a safety component; not bundled in V1).
