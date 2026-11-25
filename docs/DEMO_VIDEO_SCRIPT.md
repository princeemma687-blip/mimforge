# Demo video script (plan §6.1 — 2 min 45 s, hard cap 3:00)

**Status: SCRIPT READY — video not yet recorded.** Recording needs
the Windows app running on Prince's laptop (installer test first),
plus screen capture. Do not record in this VM and do not fake
footage: every shot below is a real screen or a real sourced clip.

Numbers in the narration are the measured ones (see
`docs/SUBMISSION.md`). The QNX jitter figure is TBD until the QEMU
run — record that shot last, after Phase 5 lands.

| Time | Picture | Narration / on-screen text |
|---|---|---|
| 0:00–0:15 | A Nigerian classroom/lab bench; title card | "Teachers demonstrate. Students watch once — then the apparatus is packed away. We turn one demonstration into a machine that can teach it again, safely." |
| 0:15–0:40 | Teacher performs the practical at L = 90 cm (reference video); app ingests it | "A teacher records the WAEC simple pendulum practical — once, on an ordinary laptop, offline." |
| 0:40–1:05 | App: track overlay on the video, period readout, auto-drafted steps, teacher edits one step | "The app extracts the motion, transcribes the narration, and drafts the teachable steps. The teacher approves every one." |
| 1:05–1:30 | Gantry design appears; BOM tiers switch Prototype → Professional; risk assessment signed | "It designs a bench gantry that fits the school's bench and budget — three material tiers, one lesson — and no design exports until a teacher signs its risk assessment." |
| 1:30–1:55 | MuJoCo simulation runs; table fills; graph draws; **g = 9.796 m/s²**; flawed conical run flagged in red | "It simulates the machine, marks it the way WAEC marks: table, graph, slope — and recovers g. A conical swing is caught and flagged, like an examiner's precaution." |
| 1:55–2:25 | Terminal/QEMU: QNX 8.0 boots; C controller runs release-count-time; timing log with jitter figures | "The timing-critical controller runs on QNX 8.0 under QEMU, cross-built with the free SDP 8.0 — deterministic timing, with a watchdog, built and tested from the Windows app." |
| 2:25–2:45 | Lesson playing on a low-end PC; E-stop pressed on the panel → monitored stop; end card with repo URL | "One demonstration. A verified teaching machine. A lesson any school computer can play. Open source — link below." |

## Recording checklist (Prince's laptop)

- [ ] Installer test passed first (docs/PACKAGING.md §6.2 test)
- [ ] Demo project open; simulation run completed (g = 9.796 on screen)
- [ ] Real-footage tracker clip ready (blocked-pendulum slow-mo,
      `~/workspace/mimforge-assets/` — internal test use only)
- [ ] Screen capture at 1080p, app window only, no desktop clutter
- [ ] Voiceover recorded clean (or captioned text if no mic)
- [ ] Final cut ≤ 2:55 (leave 5 s margin under the 3:00 cap)
- [ ] Uploaded as **public** YouTube video; link added to
      `docs/SUBMISSION.md` and the Devpost entry
