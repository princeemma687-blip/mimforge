"""Runtime profiles, including the lean mode required by the target
hardware (Core i3/i5, 4 GB RAM, Windows 10 school and teacher machines).

Lean mode is a design constraint, not a fallback afterthought: small
model variants, models loaded and unloaded one at a time, keyframe
sampling instead of per-frame processing, and CPU-first inference with
the GPU strictly optional.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeProfile:
    mode: str = "lean"
    speech_model: str = "base"  # transcription model size
    segmentation_checkpoint: str = "tiny"  # segmentation model size
    pose_model: str = "lite"  # pose model size
    keyframe_stride: int = 5  # process 1 of every N frames when sampling
    sequential_model_loading: bool = True  # load -> run -> unload, one at a time
    prefer_gpu: bool = False  # GPU is optional, never required
    max_frames_in_memory: int = 64

    def __post_init__(self) -> None:
        # A bad profile value must fail here, at construction, not
        # surface later as an unrelated failure mid-pipeline. (The
        # segmentation/pose fields name models a later perception
        # stage will load; in this build only the speech model and
        # the keyframe stride are consumed -- see docs/SBOM.md.)
        if self.keyframe_stride < 1:
            raise ValueError(
                f"keyframe_stride must be at least 1, got {self.keyframe_stride}"
            )
        if self.max_frames_in_memory < 1:
            raise ValueError(
                "max_frames_in_memory must be at least 1, got "
                f"{self.max_frames_in_memory}"
            )
        if not self.speech_model.strip():
            raise ValueError("speech_model must not be empty")


#: Default profile for the target low-spec machines (hackathon build).
LEAN_PROFILE = RuntimeProfile()

#: Profile for a better-equipped development machine. Still offline-first;
#: only model sizes and sampling change, never the pipeline.
FULL_PROFILE = RuntimeProfile(
    mode="full",
    speech_model="small",
    segmentation_checkpoint="small",
    pose_model="full",
    keyframe_stride=1,
    sequential_model_loading=False,
    prefer_gpu=True,
    max_frames_in_memory=512,
)
