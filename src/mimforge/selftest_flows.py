"""Gate v2 real-flow probes (Stage 0, 2026-11-26).

The original frozen self-test proved the bundle could *import*
everything and *construct* the window. Run #7 still shipped two
dead features, because importing is not using: the video import
needed ffprobe (borrowed from the dev machine's PATH) and the
account surface needed a config file that only existed in the dev
tree. These probes close that gap: they run the app's REAL flows
-- probe a video, extract its audio, track an object, segment a
frame, load the speech model, read the account config -- using
ONLY resources resolved through the Resource Layer, with the OS
PATH scrubbed while they run, so nothing the host machine lends
the app can mask a missing bundle resource.

The sample clip is a generated self-test asset (a bright disc
swinging on a dark field, with a tone track). It proves the tools
work; it is never shown to users as proof of anything.

Each probe returns ``(name, ok, detail)``; the frozen self-test
fails (exit 1) when any probe fails. In a source checkout the
probes run only on request (``--self-test=flows``) and need the
packaging fetch step to have produced ``bundled/`` first.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# The colour prompt matching the generated sample clip's disc
# (pure red in BGR, drawn by setup/fetch_bundled_assets.py).
_SAMPLE_PROMPT = {
    "name": "self-test disc",
    "bgr_low": (0, 0, 200),
    "bgr_high": (80, 80, 255),
    "min_pixels": 20,
}


def _scrubbed_path() -> str:
    """A PATH with nothing on it that could lend the app a tool:
    empty on POSIX; on Windows only the system directory (the OS
    itself needs it to load DLLs -- it contains no ffmpeg)."""
    if os.name == "nt":
        return os.environ.get("SystemRoot", r"C:\Windows") + r"\System32"
    return ""


def run_flow_probes(require_bundled: bool = True) -> list[tuple[str, bool, str]]:
    """Run every probe; never raises. ``require_bundled`` (the
    frozen gate) additionally asserts each resource's source is
    the bundle itself, not a per-user or dev-override copy."""
    from . import resources

    results: list[tuple[str, bool, str]] = []

    def record(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))

    saved_path = os.environ.get("PATH", "")
    os.environ["PATH"] = _scrubbed_path()
    try:
        _run(results, resources, require_bundled)
    finally:
        os.environ["PATH"] = saved_path
    return results


def _check_source(
    results, name: str, path, require_bundled: bool
) -> bool:
    """Record the resolution probe for one resource."""
    if path is None:
        results.append((name, False, "resource did not resolve"))
        return False
    report = None
    from . import resources

    for entry in resources.describe_resolution().values():
        if entry["path"] == str(path):
            report = entry["source"]
            break
    if require_bundled and report != "bundled":
        results.append(
            (name, False, f"resolved from {report or 'unknown'}, not bundled")
        )
        return False
    results.append((name, True, f"{report}: {path}"))
    return True


def _run(results, resources, require_bundled: bool) -> None:
    # -- resolution: every registered resource, bundled-sourced.
    ffprobe = resources.ffprobe_path()
    ffmpeg = resources.ffmpeg_path()
    if not _check_source(results, "resolve ffprobe", ffprobe, require_bundled):
        return
    if not _check_source(results, "resolve ffmpeg", ffmpeg, require_bundled):
        return
    sam_dir = resources.sam_weights_dir()
    if not _check_source(results, "resolve SAM weights", sam_dir, require_bundled):
        return
    whisper_dir = resources.whisper_model_dir("base")
    if not _check_source(
        results, "resolve Whisper model", whisper_dir, require_bundled
    ):
        return
    config_path = resources.firebase_config_path()
    if not _check_source(
        results, "resolve Firebase config", config_path, require_bundled
    ):
        return
    clip = resources.sample_clip_path()
    if not _check_source(results, "resolve sample clip", clip, require_bundled):
        return

    # -- probe the sample clip with the bundled ffprobe.
    from .perception import ColourPrompt, probe_video, track_object

    try:
        info = probe_video(clip)
        ok = info.width > 0 and info.height > 0 and info.duration_s > 0
        results.append(
            (
                "probe sample clip",
                ok,
                f"{info.width}x{info.height} {info.duration_s:.1f}s "
                f"audio={info.has_audio}",
            )
        )
        if not info.has_audio:
            results.append(("probe sample clip", False, "clip has no audio"))
            return
    except Exception as exc:  # noqa: BLE001 - probe reports, never raises
        results.append(("probe sample clip", False, f"{type(exc).__name__}: {exc}"))
        return

    with tempfile.TemporaryDirectory(prefix="mimforge-flows-") as tmp:
        # -- extract its audio with the bundled ffmpeg.
        from .narration import extract_audio

        wav = Path(tmp) / "sample.wav"
        try:
            extract_audio(clip, wav)
            ok = wav.is_file() and wav.stat().st_size > 0
            results.append(("extract audio", ok, f"{wav.stat().st_size} bytes"))
            if not ok:
                return
        except Exception as exc:  # noqa: BLE001
            results.append(("extract audio", False, f"{type(exc).__name__}: {exc}"))
            return

        # -- colour-track a few frames of the swinging disc.
        try:
            track = track_object(clip, ColourPrompt(**_SAMPLE_PROMPT), stride=5)
            ok = track.frames_tracked > 0 and track.coverage > 0.5
            results.append(
                (
                    "colour-track sample frames",
                    ok,
                    f"tracked {track.frames_tracked}/{track.frames_total} "
                    f"examined frames",
                )
            )
            if not ok:
                return
        except Exception as exc:  # noqa: BLE001
            results.append(
                ("colour-track sample frames", False, f"{type(exc).__name__}: {exc}")
            )
            return

        # -- load the bundled Whisper model and run it on the tone
        #    (a tone carries no speech: success = it runs clean).
        try:
            from faster_whisper import WhisperModel

            model = WhisperModel(
                str(whisper_dir), device="cpu", compute_type="int8"
            )
            segments, _info = model.transcribe(str(wav), beam_size=1)
            list(segments)  # generation is lazy; force the run
            del model
            results.append(("load Whisper model + transcribe tone", True, "ran"))
        except Exception as exc:  # noqa: BLE001
            results.append(
                (
                    "load Whisper model + transcribe tone",
                    False,
                    f"{type(exc).__name__}: {exc}",
                )
            )
            return

    # -- segment one frame with the bundled SAM weights.
    try:
        from .perception import iter_frames
        from .sam_tracker import SamSegmenter, weights_present

        if not weights_present(sam_dir):
            results.append(("segment frame with SAM", False, "weights fail hash check"))
            return
        frame = None
        for _index, _t, first in iter_frames(clip, stride=1):
            frame = first
            break
        if frame is None:
            results.append(("segment frame with SAM", False, "no frame read"))
            return
        segmenter = SamSegmenter(folder=sam_dir)
        height, width = frame.shape[:2]
        mask = segmenter.segment(frame, (width // 2, height // 2))
        ok = mask is not None and bool(mask.any())
        results.append(("segment frame with SAM", ok, "mask returned" if ok else "empty mask"))
        if not ok:
            return
    except Exception as exc:  # noqa: BLE001
        results.append(("segment frame with SAM", False, f"{type(exc).__name__}: {exc}"))
        return

    # -- the bundled Firebase config parses and is usable.
    try:
        from .firebase_sync import load_firebase_config

        config = load_firebase_config()
        ok = config is not None and config.usable
        results.append(
            (
                "load Firebase config",
                ok,
                "usable config loaded" if ok else "no usable config",
            )
        )
    except Exception as exc:  # noqa: BLE001
        results.append(("load Firebase config", False, f"{type(exc).__name__}: {exc}"))

    _probe_machine_view(results)
    _probe_narration(results)


def _probe_narration(results) -> None:
    """Stage 2 Gate v2 probe: talking lessons, exercised in this
    scrubbed environment. The BUNDLED Piper voice + lexicon must
    resolve through the Resource Layer and synthesize one step of
    neutral text into non-silent audio, and the attach flow must
    stamp the step with the plain-words AI voice label. Kokoro is
    probed too when bundled: it must also produce non-silent
    audio. A lesson with no working voice would still play
    silently -- but then this probe fails, because the shipped
    build promises a voice."""
    try:
        from . import resources, speech
        from .playback import LessonPackage, LessonStep

        _check_source(
            results,
            "resolve Piper voice",
            resources.piper_voice_dir(),
            require_bundled=True,
        )
        engine = speech.piper_engine()
        if engine is None:
            results.append(
                ("narration synthesis", False, "Piper voice did not resolve")
            )
            return
        text = "The machine is ready. Watch the moving part, then read the scale."
        wav, duration = engine.synthesize(text)
        rms = speech.wav_rms(wav)
        ok = duration > 0.8 and rms > 0.005
        results.append(
            (
                "narration synthesis",
                ok,
                f"piper {engine.voice}: {duration:.1f}s audio, rms {rms:.3f}",
            )
        )
        if not ok:
            return
        import tempfile
        from pathlib import Path

        lesson = LessonPackage(
            title="Probe",
            subject="Probe",
            template_id="probe",
            steps=[LessonStep(order=1, title="Probe step", narration=text)],
        )
        with tempfile.TemporaryDirectory() as tmp:
            report = speech.attach_narration(
                lesson, engine=engine, cache_dir=Path(tmp)
            )
        step = lesson.steps[0]
        labelled = (
            report.ai_steps == 1
            and step.audio is not None
            and step.audio.label == speech.AI_VOICE_LABEL
            and step.audio.source == "ai"
        )
        results.append(
            (
                "narration label",
                labelled,
                f"attach report ai_steps={report.ai_steps}; "
                f"label={step.audio.label if step.audio else None!r}",
            )
        )
        kokoro = speech.KokoroEngine()
        if kokoro.available():
            kwav, kduration = kokoro.synthesize(text)
            krms = speech.wav_rms(kwav)
            results.append(
                (
                    "narration kokoro",
                    kduration > 0.8 and krms > 0.005,
                    f"kokoro-82m: {kduration:.1f}s audio, rms {krms:.3f}",
                )
            )
    except Exception as exc:  # noqa: BLE001
        results.append(
            ("narration synthesis", False, f"{type(exc).__name__}: {exc}")
        )


def _probe_machine_view(results) -> None:
    """Stage 1 Gate v2 probe: the living machine, exercised in
    this scrubbed environment. When a GL renderer is available,
    the three views must render living, differing frames inside
    the frame-time budget. When it is not, the probe passes on
    the fallback path instead -- the canvas performance view must
    construct and draw -- because the fallback is a designed
    behaviour, while a crash or a blank panel is not."""
    try:
        from . import visuals
        from .design import GantryParameters

        params = GantryParameters()
        timeline = visuals.MachineTimeline.rest(params)
        state = timeline.state_at(0.0)
        if visuals.renderer_available():
            renderer = visuals.MachineRenderer(params, width=320, height=240)
            frames = {
                view: renderer.render(state, view)
                for view in ("front", "side", "top")
            }
            alive = all(visuals.frame_is_alive(f) for f in frames.values())
            differ = not (
                (frames["front"] == frames["side"]).all()
                or (frames["front"] == frames["top"]).all()
            )
            median_ms = renderer.measure_median_frame_ms(state, frames=15)
            renderer.close()
            ok = alive and differ and median_ms < 100.0
            results.append(
                (
                    "machine view render",
                    ok,
                    f"median {median_ms:.1f} ms/frame at 320x240; "
                    f"views alive={alive} differ={differ}",
                )
            )
        else:
            results.append(
                (
                    "machine view render",
                    True,
                    "renderer unavailable here -- fallback path probed below",
                )
            )
        # The fallback path must exist and draw, in both worlds.
        from PySide6.QtWidgets import QApplication

        if QApplication.instance() is not None:
            from .ui.machine_view import MachineViewWidget

            widget = MachineViewWidget(force_fallback=True)
            widget.set_timeline(timeline, "PROBE")
            widget.render_frame_now()
            ok = widget.using_fallback and widget.pages.currentIndex() == 1
            widget.set_view("internals")
            ok = ok and widget.pages.currentIndex() == 2
            results.append(
                (
                    "machine view fallback",
                    ok,
                    "canvas performance + internals pages draw offscreen",
                )
            )
            widget.close()
    except Exception as exc:  # noqa: BLE001
        results.append(
            ("machine view render", False, f"{type(exc).__name__}: {exc}")
        )


def flows_main() -> int:
    """Console entry for the flow probes: prints one line per
    probe and returns 0 only when every probe passed."""
    frozen = bool(getattr(sys, "frozen", False))
    results = run_flow_probes(require_bundled=True)
    failed = 0
    for name, ok, detail in results:
        print(f"FLOW {'OK  ' if ok else 'FAIL'} {name} -- {detail}", flush=True)
        if not ok:
            failed += 1
    if failed:
        print(f"SELF-TEST FLOWS FAILED ({failed} probe(s))", flush=True)
        return 1
    print("SELF-TEST FLOWS OK", flush=True)
    return 0
