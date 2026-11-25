# Filming Protocol — Pendulum Reference Demonstrations

**Purpose (Phase 0, step 0.3):** produce the two reference videos the
engine is developed and tested against — a **clean run** and a
**deliberately flawed (conical) run** — following the protocol in the
project plan (§5.1). Test for this step: both videos play, are hashed
(SHA-256), and the flawed run is *visibly* conical.

## Consent — read first

- **Record the teacher, not the students.** Film in an empty lab or with
  the camera framed so no student is identifiable. No student video by
  design.
- The demonstrating teacher signs a consent record **before** filming:
  who is recorded, the scope (capture / processing / sharing), the date,
  and how to withdraw. Withdrawal deletes the local media and any shared
  metadata. (Nigeria Data Protection Act 2023: recorded people are
  personal data; consent records are stored with the project.)
- Narrate as if teaching, but do not name any student.

## Apparatus

- Retort stand with clamp (heavy base, on a firm bench)
- Split cork (to grip the thread at the pivot)
- Thread (inextensible, ~1.2 m)
- Pendulum bob — **painted a high-contrast colour** (e.g. bright orange)
  so tracking can follow it against the background
- Metre rule
- Stopwatch
- Fiducial mark: a thin card/line fixed at the equilibrium position,
  behind the bob's rest position
- Spirit level / set square (optional, for checking the swing plane)

## Camera setup

- **Fixed tripod** — the camera must not move between or during runs.
- **Side-on** to the swing plane, lens axis perpendicular to the plane of
  oscillation, centred on the bob's rest position.
- Frame: whole swing visible at L = 90 cm with margin; the metre rule and
  the fiducial mark visible in frame.
- **Plain, contrasting background** behind the swing (a plain sheet/board
  if the lab wall is cluttered); even lighting, no flicker, no window
  glare behind the bob.
- Highest resolution the camera allows at a fixed frame rate; lock
  exposure/focus if the camera permits. Landscape orientation.
- Keep the original file untouched; the engine works on a normalised
  copy. Hash the original (SHA-256) and record the hash with the consent
  record.

## Run 1 — Clean demonstration (motion-extraction reference)

Perform the full WAEC sequence exactly as a candidate should, narrating
each step aloud (narration is transcribed and aligned to steps):

1. Set up: stand, clamp, split cork, thread, bob. State that zero error
   was checked. Measure and say aloud: **L is measured from the pivot to
   the centre of the bob.**
2. Set **L = 90.0 cm**. Displace the bob through a **small angle
   (≤ ~10°)**, release **without a push**, keeping the swing in one
   vertical plane.
3. Time **20 complete oscillations**, starting/stopping as the bob
   crosses the fiducial mark. Repeat the timing (t₁ and t₂).
4. Repeat steps 2–3 for **L = 80, 70, 60, 50 cm** (shorten the thread at
   the split cork each time; re-measure and state L aloud).
5. Close by stating the two precautions, in the past tense, exactly as a
   candidate should write them:
   - the bob was displaced through a small angle and released without a
     push, and conical oscillation was avoided;
   - timing was started and stopped at the fiducial mark, and the
     support was firm / shielded from draught.

Expected reference readings (sanity check, from the plan's worked
example — your real readings will differ slightly and that is fine):
mean t for 20 oscillations ≈ 38.1 / 35.9 / 33.6 / 31.1 / 28.4 s for
L = 90 / 80 / 70 / 60 / 50 cm.

## Run 2 — Deliberately conical run (discrepancy-engine test)

Same setup, L = 90 cm only:

1. Displace the bob and release it **with a sideways component** (a small
   push at an angle to the swing plane) so the bob settles into a clearly
   **elliptical / conical path** instead of a plane swing.
2. Let it run for at least 20 oscillations on camera. Narrate plainly:
   "This run is deliberately wrong — the swing is conical."
3. If the first attempt decays into a plane swing too quickly, re-film
   with a slightly larger sideways release. The test needs the
   ellipticity to be visible to the eye in the raw video.

## File handling

- Suggested names: `pendulum_clean_YYYYMMDD.mp4`,
  `pendulum_conical_YYYYMMDD.mp4` (local project folder only — videos are
  never committed to git; see `.gitignore`).
- Record for each file: SHA-256 hash, date, demonstrator (consent on
  file), camera used, lengths covered.
- Verify before leaving the lab: both files play end to end; the clean
  run's bob is trackable (in frame, contrasted) in every length segment;
  the conical run is visibly conical.
