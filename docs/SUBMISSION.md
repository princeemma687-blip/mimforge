# QNX Global Hackathon — submission package (draft, Phase 6.3)

**Status: DRAFT — do not submit yet.** The app build is complete;
two items remain before submission: (1) the QNX SDP 8.0 install +
first real `qcc` cross-build + QEMU run (needs Prince's one-time
myQNX sign-in — Phase 5, parked), and (2) the demo video recording
(on Prince's Windows laptop, script in `docs/DEMO_VIDEO_SCRIPT.md`).
Prince registers and submits himself from 10 December 2026 (age
rule: 18+ at entry). Internal submit-by date: **14 December 2026**
(deadline 15 Dec 2026, 2:00 pm ET = 20:00 WAT).

## Devpost draft

**Project name:** Mimforge

**Tagline:** Teachers demonstrate once. Mimforge turns the
demonstration into a teaching machine that can teach it again,
safely.

**Category:** Robotics & Medical

**Description (draft):**

> A teacher demonstrates a practical once — on an ordinary laptop,
> offline — and Mimforge turns that single demonstration into a
> teaching machine that can perform it again for every class, with
> the safety a room full of learners demands.
>
> The pipeline is practical-agnostic: ingest a demonstration
> video, extract the motion and transcribe the narration locally,
> structure it into teacher-approved steps, design the machine
> from a parameterised platform library (bench gantry first),
> generate its control code and control panel, price the build in
> three tiers, simulate the machine before anything moves, compare
> the simulation against the teacher's demonstration, and block
> export until a teacher signs the risk assessment. Lesson
> packages are signed, hash-verified, and play back on any
> low-spec school PC with no engine and no network.
>
> The first worked example is the WAEC Physics simple pendulum
> practical (determination of g). From the teacher's video the
> app recovers the readings table, draws the graph, and recovers
> g = 9.796 m/s² against the true 9.81 (−0.14%) through the
> identical table → graph → slope pipeline a candidate follows.
> A conical swing is flagged with the examiner's own diagnosis;
> a seeded length error is caught and auto-corrected.
>
> **QNX evidence:** the timing-critical controller — the
> release / count / time loop — is implemented in C in `qnx/`,
> with a host build and a 93-check test suite passing. It is
> cross-built with the free QNX SDP 8.0 and run under QEMU from
> the Windows app, which builds, deploys and tests the target
> and ingests its timing log (host-tool route). The timing log
> with measured jitter is in `qnx/` (pending the SDP install
> step — see below).
>
> **What QNX is for, honestly:** the product does not need QNX
> to run — the V1 machines can run the Linux/Python controller.
> QNX is where the deterministic part lives: the release/count/
> time loop is a real real-time workload, and the hackathon is
> the deadline that forced V1 to exist. Only the controller loop
> is ported, by design; porting the whole app would sink the
> deadline.
>
> Built for Nigerian schools first: offline-first, lean mode for
> Core i3 / 4 GB machines, $0 services throughout, Apache-2.0.

**Repo:** https://github.com/princeemma687-blip/mimforge (public,
Apache-2.0 — licence file visible at repo root)

**Demo video:** under 3 minutes, public YouTube (link added after
recording — script in `docs/DEMO_VIDEO_SCRIPT.md`).

**Build / run instructions (for the judges):**

```powershell
# Windows (the supported host)
.\setup\windows-toolchain.ps1   # Python 3.11+, LGPL FFmpeg build
.\setup\build-windows.ps1       # full test suite gate, then
                                # PyInstaller app + Inno Setup installer
# or run from source:
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -e .; pytest; python -m mimforge
```

```bash
# QNX target (needs QNX SDP 8.0, free non-commercial licence)
# See qnx/README.md for the exact install + cross-build commands
# and the QEMU run. Host build + tests (no SDP needed):
cd qnx && make test
```

## Submission checklist (walked against the official rules page)

- [x] Public repo, OSI licence visible (Apache-2.0, `LICENSE`)
- [x] Build/run instructions state QNX version (8.0), QEMU target,
      toolchain (`qcc` via SDP 8.0) — in `qnx/README.md`
- [x] QNX evidence in repo: `qnx/` C controller + host build +
      93-check test suite (all passing, `make test`)
- [ ] QNX cross-build + QEMU run with measured timing log
      (Phase 5 — needs Prince's myQNX sign-in; then `qnx/` log
      file is linked here)
- [ ] Demo video < 3 min, public YouTube (script ready; record
      on Prince's laptop after the Windows installer test)
- [ ] Devpost text above pasted + category Robotics & Medical
- [ ] Submitted by 14 Dec 2026 (Prince registers from 10 Dec)

## Measured numbers quoted in the submission (all verified in-repo)

| Claim | Number | Source |
|---|---|---|
| Recovered constant, video extraction | 9.796 (−0.14% vs 9.81) | `experiments/pendulum_proof/` |
| Recovered constant, MuJoCo gantry sim | 9.796 (−0.14%), slope 4.030 | Phase 4, test T4.2 |
| Real-footage tracker coverage | 100% (600/600 frames, 0 gaps) | `experiments/real_footage_track.py` |
| Test suite | 120 tests passing | `pytest` |
| QNX C controller checks | 93 checks passing | `qnx/tests/`, `make test` |
| Allow-list checker | fails 12 seeded malicious samples | `tests/test_allowlist.py` |
| QNX timing jitter | **TBD — pending QEMU run** | Phase 5 |

No number in the submission text is invented: anything marked TBD
stays TBD until the QEMU run measures it.
