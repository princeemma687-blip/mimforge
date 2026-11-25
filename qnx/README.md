# Mimforge timing controller — QNX target component

The real-time heart of a Mimforge-generated machine: a **generic
timing/counting controller** written in portable C99. This is the one
component the project plan (Phase 5) ports to **QNX Neutrino 8.0**,
cross-built with the free **QNX SDP 8.0** and run under **QEMU**,
because release/count/time loops are deadline-bound work where a
deterministic RTOS is genuinely the right tool — and because the QNX
Global Hackathon requires genuine QNX build/run evidence, not a
mention in a README.

## Status — read this first

| Piece | State |
|---|---|
| Controller core (`src/timing_controller.c`) | **Built and tested on the host** (gcc, Linux) |
| Host platform layer + test harness | **Built and passing: 93 checks, 0 failures** |
| QNX platform layer (`src/platform_qnx.c`) | Written against the QNX 8.0 API, **NOT compiled or run** |
| QNX entry point (`src/main_qnx.c`) | Written, **NOT compiled or run** |
| QNX SDP 8.0 download / install | **NOT done** — the free non-commercial SDP 8.0 licence is deployed to the owner's myQNX account, and QNX Software Center 2.0.4 is installed on this VM at `~/qnx/qnxsoftwarecenter` (headless install 2026-11-25, `qnxsoftwarecenter_clt` 2.0.4 verified working). The SDP install itself needs the owner's myQNX sign-in (password) — his step, not attempted here. Ready command, once signed in: `qnxsoftwarecenter_clt -syncLicenseKeys -myqnx.user=<user> -myqnx.password=<password>` then `qnxsoftwarecenter_clt -cleanInstall -destination ~/qnx800 -installBaseline com.qnx.qnx800 -myqnx.user=<user> -myqnx.password=<password>` (baseline id from QNX's own unattended-install docs). |
| Devpost / hackathon registration | **NOT done** — owner's step, untouched here |
| QEMU run of the QNX image | **NOT done** — happens after the SDP install |

Nothing in this directory has been compiled with `qcc` or executed on
QNX. Every number quoted below is from the **host build with a virtual
clock**, labelled as such.

## What the controller does

A machine step of the form *release something, then count sensor edges
for N complete cycles while timing each cycle* is everywhere in
practical work — timing oscillations through an optical gate is the
first demo's instance. The controller generalises it:

- **Parameterised cycle counting** — a cycle is `edges_per_cycle`
  accepted sensor edges (2 for a gate at a symmetry point, 1 for a
  once-per-revolution marker, …). Configuration, not code.
- **High-resolution period measurement** — every cycle's period is
  recorded from a monotonic nanosecond clock; results report elapsed
  time, mean/min/max period and jitter (max deviation from the mean).
- **Release/trigger timing** — arming, then a release command that
  drives the platform's release output and stamps the time; the
  release-to-first-edge interval is measured and reported.
- **Watchdog** — two independent trips while a run is active:
  no accepted sensor edge within `watchdog_timeout_ns`, or the
  supervising loop missing its `kick_deadline_ns`. Either faults the
  run and drives the output safe.
- **Monitored stop (E-stop)** — a hardware stop input (polled) or a
  software `tc_estop()` latches the ESTOP state from *any* state: the
  release output is driven safe, sensor edges are ignored, and only a
  deliberate `tc_reset()` returns to IDLE. A stop never auto-resumes.
- **Plausibility window** — a completed cycle whose period falls
  outside the configured `[min_period_ns, max_period_ns]` faults the
  run instead of silently recording bad data.
- **Glitch rejection** — edges arriving sooner than
  `min_edge_interval_ns` after the previous accepted edge are counted
  as rejected and never disturb the timing.

State machine: `IDLE → ARMED → RELEASED → RUNNING → COMPLETE`, with
`ESTOP` and `FAULT` reachable from the active states and cleared only
by deliberate reset.

## Design: platform abstraction layer

The core contains **no platform calls** except the five functions in
`include/platform.h`:

```c
uint64_t plat_now_ns(void);        /* monotonic nanosecond clock   */
void     plat_release_set(bool);   /* release/trigger output       */
bool     plat_release_get(void);   /* last commanded output state  */
bool     plat_estop_requested(void); /* hardware stop input        */
void     plat_log(const char *, ...); /* diagnostic sink           */
```

Retargeting is a **platform-file swap**, never a core rewrite:

| Build | Platform file | Clock | I/O |
|---|---|---|---|
| Host (this repo's tests) | `src/platform_host.c` | Virtual clock driven by the harness — fully deterministic tests | Simulated in memory |
| QNX 8.0 (Phase 5) | `src/platform_qnx.c` | `ClockCycles()` scaled by the syspage cycles/sec | State + log under QEMU; board GPIO is a marked TODO for real hardware |
| Future microcontroller | a new `platform_<board>.c` | board timer | board GPIO |

`src/main_qnx.c` shows the intended on-target shape: a control thread
at real-time priority (`SCHED_FIFO`) owns the controller (kick, poll,
edge feed), and — for the QEMU timing test (plan test T5.2) — a
simulation thread toggles the gate level at a configured period in
place of the physical optical gate.

## Host build and test results

```sh
make test        # gcc -std=c99 -Wall -Wextra -Werror -O2
```

The harness (`tests/test_timing_controller.c`) drives the controller
through the virtual clock and feeds synthetic gate edges derived from
the demo template's worked-example data (test data only — the core
stays generic; a scan confirms no demo specifics in `src/` or
`include/`). Measured results from the run on 2026-11-25:

- **Worked example reproduced exactly.** Timing 20 cycles at five
  settings, the controller's measured mean times matched the template
  table to the nanosecond (38.100000000 s, 35.900000000 s,
  33.600000000 s, 31.100000000 s, 28.400000000 s — worst deviation
  0.000000 s at printed precision, as expected from a virtual clock).
  Least-squares slope of the squared-period values: **4.0292 s²/m**
  (template: 4.03); derived constant **9.7980** against the expected
  9.81 — an error of **−0.12 %**, inside the template's ±5 % tolerance
  band and its ±3 % target band.
- **Jitter:** with ±2 ms of deterministic pseudo-random edge jitter,
  the mean period measured 1.905146 s against a true 1.905000 s
  (0.008 % error), reported jitter 0.003749 s, zero false glitch
  rejections.
- **Glitch rejection:** 10 injected bounce edges (5 ms after real
  edges) were all rejected; 41 real edges accepted; the measured mean
  time was undisturbed (28.4000 s).
- **Watchdogs:** an edge gap of 6 s against a 5 s timeout faulted the
  run (`WATCHDOG_EDGE_GAP`) with the output driven safe; a supervising
  loop that stopped kicking faulted at its 2 s deadline
  (`WATCHDOG_KICK`); a correctly kicked loop ran clean.
- **Monitored stop:** latched from mid-run, stayed latched after the
  input cleared, ignored further edges, refused resume, and recovered
  only via deliberate reset — after which the controller ran again.
- **Plausibility window:** cycles of 1.2 s against a [1.6 s, 2.2 s]
  window faulted the run (`PERIOD_WINDOW`) with the output safe.
- **Total: 93 checks, 0 failures**, compiled clean under
  `-Wall -Wextra -Werror`.

Honest limits of the host proof: the virtual clock makes clean runs
exact by construction — the host tests prove the controller's
*logic* (counting, state machine, watchdogs, stop behaviour, result
maths), not real-world timing accuracy. Real jitter numbers come from
the QEMU target run (plan test T5.2) and later from hardware.

## The QNX cross-build (Phase 5 — later, owner's SDP required)

`Makefile.qnx` is committed and documents the exact steps:

1. The project owner creates a myQNX account and installs **QNX SDP
   8.0** via QNX Everywhere (free for non-commercial use) on the build
   host, then sources `qnxsdp-env.sh`.
2. `make -f Makefile.qnx` — compiles `timing_controller.c` +
   `platform_qnx.c` + `main_qnx.c` with
   `qcc -Vgcc_ntox86_64` for the x86_64 QEMU target. The core needs no
   changes; only the platform file differs from the host build.
3. Boot the QNX 8.0 x86_64 image under QEMU, transfer the binary, run
   `./mimforge_controller_qnx 1.905` — it times 20 cycles from the
   simulated gate input and prints the timing log (state, cycles,
   elapsed, mean period, jitter) that the Mimforge host app ingests.
   Build/run instructions for the submission must state: QNX version
   (8.0), target (x86_64 QEMU), toolchain (QNX SDP 8.0 / qcc).
4. Expected first-build friction (untested code, stated plainly):
   `platform_qnx.c` / `main_qnx.c` have never been compiled — minor
   API or header fixes on first `qcc` contact are likely and are part
   of the Phase 5 task, not a surprise.

Licence note: QNX SDP's free licence is **non-commercial**. QNX is
the hackathon target and a high-integrity option; shipped machines
can run the Linux/Python controller instead. That decision (plan D6)
belongs to the owner.

## Minimal SDP package set for Phase 5 (research, 2026-11-26)

Prince's download comfort line is **~2 GB** on his own connection;
above that needs outside Wi-Fi. The full baseline does **not** fit
that line, so the guided SDP session should install the smallest set
that still does the Phase 5 job (qcc cross-build + `mkqnximage` +
QEMU run). Researched from QNX's own docs (QSC User's Guide,
Command Line chapter; QNX Everywhere resources) and the
QNX Global Hackathon community tutorial (dev.to, replayed
2026-11-09). **Nothing in this section was verified by an install —
exact package IDs and download sizes are only visible after the
owner's myQNX sign-in, so the session must confirm them live.**

What Phase 5 actually needs (nothing else):

| Need | Where it comes from |
|---|---|
| `qcc` cross-compiler (Linux host, x86_64) | SDP host toolchain package |
| x86_64 target headers + libs (`QNX_TARGET`) | SDP x86_64 target package |
| `mkqnximage` (builds the QEMU image locally) | SDP host-common tools |
| QEMU itself (`qemu-system-x86`, ~49 MB) | host OS package manager (`apt`), **not** QNX |

What to **skip** (the big items):

- **Quick Start QEMU image package — 20.0 GB installed.** Skip it;
  build the image locally with `mkqnximage` (~170 MB image).
  (dev.to tutorial, step 3.)
- **Momentics IDE** and any other target architectures (aarch64) —
  not needed for a `qcc` + QEMU job.
- Docs/examples if the installer lets them be deselected.

Size facts (all "installed size" as the Software Center lists it;
download is the compressed `.qpkg`, smaller, but QNX publishes no
download-size table):

- Full baseline `com.qnx.qnx800`: **~6.4 GB installed** (Build 141,
  per the dev.to tutorial; one install measured 3.5 GB on disk).
  Download is "several GB" — **above the 2 GB line**.
- **Verdict: a sub-2 GB download is NOT proven achievable.** The
  minimal set is plausibly 1–3 GB, but only the signed-in Software
  Center shows per-package sizes, so the session must check before
  downloading. If the minimal set still exceeds ~2 GB, the session
  needs plugged-in outside Wi-Fi (the 6.4 GB figure is the data
  problem Prince named on 2026-11-25, ~₦29,000 on PAYG mobile data —
  never download the SDP on mobile data).

Mechanism (QSC Command Line chapter, qnx.com):

- Install individual packages instead of the whole baseline:
  `qnxsoftwarecenter_clt -installPackage 'com.qnx.qnx800.<id>' ...`
  (several IDs in one `-installPackage` call; `-Dbase=qnx800`
  variable form documented, e.g.
  `com.qnx.${base}.target.driver.virtio`).
- After sign-in, enumerate what exists before choosing:
  `qnxsoftwarecenter_clt -listAccessible` and
  `-listQuery 'Q:latest()'` (package IDs + versions; sizes shown in
  the GUI's package list).
- QSC 2.0.3+ also has an **unmanaged** mode (`-installPackage` /
  `-downloadPackage` without dependency resolution) for a hand-picked
  set — use only if the managed install pulls in the full baseline.
- In the GUI, "Add Installation" shows the baseline's packages and
  lets components be deselected before download starts.

Package-ID patterns seen in public QNX material (patterns only —
**confirm the real IDs with `-listQuery` in the session, do not
guess them into a command**):

- `com.qnx.qnx800.host.<os>.<arch>.<component>` — e.g.
  `com.qnx.qnx800.host.win.x86_64.rust` (QNX CI blog).
- `com.qnx.qnx800.target.<...>` — e.g.
  `com.qnx.qnx800.target.driver.virtio` (CLT doc example).

Local check done 2026-11-26: `qnxsoftwarecenter_clt -list` without
sign-in fails (`allrepos` is null) — package enumeration genuinely
needs the owner's sign-in, confirming this stays a live-session step.

In-session checklist (Prince's guided session, after sign-in):

1. `-syncLicenseKeys`, then `-listAccessible` / GUI package list.
2. Note the per-package sizes; pick host toolchain + x86_64 target
   + host-common (`mkqnximage`) only; deselect IDE, aarch64, docs,
   Quick Start image.
3. If the total download is ≤ ~2 GB, proceed on his connection;
   otherwise stop and move the session to outside Wi-Fi.
4. `source ~/qnx800/qnxsdp-env.sh`; `which qcc mkqnximage` must
   resolve; then `make -f Makefile.qnx` + the QEMU run in this repo.

## Files

```
qnx/
├── README.md                  this file
├── Makefile                   host build (gcc) + tests
├── Makefile.qnx               QNX SDP 8.0 target build (not yet run)
├── include/
│   ├── platform.h             platform abstraction layer (5 functions)
│   ├── platform_host.h        host-only test hooks (virtual clock)
│   └── timing_controller.h    controller API, config, results
├── src/
│   ├── timing_controller.c    generic core (platform-independent)
│   ├── platform_host.c        host PAL: virtual clock, simulated I/O
│   ├── platform_qnx.c         QNX PAL (guarded __QNXNTO__, uncompiled)
│   └── main_qnx.c             QNX entry point (guarded, uncompiled)
└── tests/
    └── test_timing_controller.c  host harness: 93 checks
```
