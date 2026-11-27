"""Episode discipline for demonstrations (Stage 5, plan section 10.1).

One imported demonstration is one *episode* of the project's
demonstration set -- the dataset discipline the LeRobot work is
known for, applied to the data this app already stores. An episode
is numbered, carries the quality flags the import already measured
(track coverage as measured, the recovered period where the track
supports one), and carries the teacher's verdict. The set is a
project record (kind ``"episodes"``, id ``"set"``), so it survives
reopen exactly like every other project record, and it travels in
the signed package as ``episodes.json`` (see ``delivery``).

Everything here is generic: an episode names a demonstration
record, never a practical, a subject or a shape. The per-episode
flags are snapshots taken at import time, so the set stays readable
even if the demonstration record itself is later removed -- that
case is reported as a missing demonstration, never silently hidden.

A project created before episodes existed holds a demonstration
record under id ``"current"`` with no set. Opening such a project
adopts that recording as episode 1 (``adopt_legacy``); the adoption
is deterministic, so re-opening re-adopts identically until a set
record is saved.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

__all__ = [
    "EPISODES_KIND",
    "EPISODES_RECORD_ID",
    "Episode",
    "DemonstrationSet",
    "EpisodeError",
    "VERDICTS",
    "demonstration_set",
    "episode_record_id",
    "save_demonstration_set",
]

EPISODES_KIND = "episodes"
EPISODES_RECORD_ID = "set"

# The teacher's verdict on one episode. "not-set" is the default:
# an episode with no verdict has simply not been judged yet, and
# nothing in the pipeline treats an unjudged episode as approved.
VERDICTS = ("not-set", "approved", "needs-work")


class EpisodeError(Exception):
    """An episode record is malformed, duplicated, or unusable."""


def episode_record_id(number: int) -> str:
    """The demonstration record id an episode points at."""
    return f"episode-{number}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Episode:
    """One demonstration episode: numbered, flagged, judged."""

    number: int
    demonstration_id: str
    source_name: str = ""
    tracker: str = ""
    coverage: Optional[float] = None
    period_s: Optional[float] = None
    video_sha256: str = ""
    verdict: str = "not-set"
    verdict_by: str = ""
    imported_at: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.number, int) or isinstance(self.number, bool):
            raise EpisodeError(f"episode number must be an integer: {self.number!r}")
        if self.number < 1:
            raise EpisodeError(f"episode number must be 1 or more: {self.number}")
        if not isinstance(self.demonstration_id, str) or not self.demonstration_id:
            raise EpisodeError("episode needs a demonstration id")
        if "/" in self.demonstration_id or "\\" in self.demonstration_id:
            raise EpisodeError(
                f"unsafe demonstration id: {self.demonstration_id!r}"
            )
        if self.coverage is not None:
            if not isinstance(self.coverage, (int, float)) or isinstance(
                self.coverage, bool
            ):
                raise EpisodeError(f"coverage must be a number: {self.coverage!r}")
            if math.isnan(self.coverage) or math.isinf(self.coverage):
                raise EpisodeError("coverage must be a finite number")
            if not 0.0 <= float(self.coverage) <= 1.0:
                raise EpisodeError(
                    f"coverage must be between 0 and 1: {self.coverage}"
                )
            self.coverage = float(self.coverage)
        if self.period_s is not None:
            if not isinstance(self.period_s, (int, float)) or isinstance(
                self.period_s, bool
            ):
                raise EpisodeError(f"period must be a number: {self.period_s!r}")
            if math.isnan(self.period_s) or math.isinf(self.period_s):
                raise EpisodeError("period must be a finite number")
            if float(self.period_s) < 0:
                raise EpisodeError(f"period must not be negative: {self.period_s}")
            self.period_s = float(self.period_s)
        if self.verdict not in VERDICTS:
            raise EpisodeError(f"unknown teacher verdict: {self.verdict!r}")
        if not isinstance(self.source_name, str):
            raise EpisodeError("source name must be text")
        if not isinstance(self.tracker, str):
            raise EpisodeError("tracker name must be text")

    # ------------------------------------------------------------ serialise

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "demonstration_id": self.demonstration_id,
            "source_name": self.source_name,
            "tracker": self.tracker,
            "coverage": self.coverage,
            "period_s": self.period_s,
            "video_sha256": self.video_sha256,
            "verdict": self.verdict,
            "verdict_by": self.verdict_by,
            "imported_at": self.imported_at,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "Episode":
        """Rebuild one episode, refusing anything malformed.

        A corrupt episode record must never load as a plausible
        episode: wrong types, missing keys, out-of-range numbers
        and unknown verdicts all raise :class:`EpisodeError`."""
        if not isinstance(data, dict):
            raise EpisodeError("episode record must be an object")
        try:
            return cls(
                number=data["number"],
                demonstration_id=data["demonstration_id"],
                source_name=data.get("source_name", ""),
                tracker=data.get("tracker", ""),
                coverage=data.get("coverage"),
                period_s=data.get("period_s"),
                video_sha256=data.get("video_sha256", ""),
                verdict=data.get("verdict", "not-set"),
                verdict_by=data.get("verdict_by", ""),
                imported_at=data.get("imported_at", ""),
            )
        except KeyError as exc:
            raise EpisodeError(
                f"episode record is missing {exc.args[0]}"
            ) from None
        except (TypeError, ValueError) as exc:
            raise EpisodeError(f"episode record is malformed: {exc}") from None


@dataclass
class DemonstrationSet:
    """The numbered episodes of one project, in number order."""

    episodes: list[Episode] = field(default_factory=list)

    def __post_init__(self) -> None:
        numbers = [e.number for e in self.episodes]
        if len(numbers) != len(set(numbers)):
            raise EpisodeError("demonstration set holds a duplicate episode number")
        self.episodes.sort(key=lambda e: e.number)

    # ------------------------------------------------------------ numbering

    def next_number(self) -> int:
        """The number the next imported demonstration takes."""
        if not self.episodes:
            return 1
        return max(e.number for e in self.episodes) + 1

    def add(self, episode: Episode) -> None:
        """Append one episode; a duplicate number is refused."""
        if any(e.number == episode.number for e in self.episodes):
            raise EpisodeError(
                f"episode {episode.number} already exists in this project"
            )
        self.episodes.append(episode)
        self.episodes.sort(key=lambda e: e.number)

    def get(self, number: int) -> Optional[Episode]:
        for episode in self.episodes:
            if episode.number == number:
                return episode
        return None

    # ------------------------------------------------------------ verdicts

    def set_verdict(
        self, number: int, verdict: str, by: str = ""
    ) -> Episode:
        """Record the teacher's verdict on one episode.

        Raises :class:`EpisodeError` for an unknown episode number
        or an unknown verdict value; the set is unchanged then."""
        if verdict not in VERDICTS:
            raise EpisodeError(f"unknown teacher verdict: {verdict!r}")
        episode = self.get(number)
        if episode is None:
            raise EpisodeError(f"no episode {number} in this project")
        episode.verdict = verdict
        episode.verdict_by = str(by or "")
        return episode

    # ------------------------------------------------------------ serialise

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "episodes": [e.to_dict() for e in self.episodes],
        }

    @classmethod
    def from_dict(cls, data: Any) -> "DemonstrationSet":
        """Rebuild a set, refusing anything malformed: a wrong
        version, a non-list of episodes, a duplicate episode
        number, or any single corrupt episode all raise
        :class:`EpisodeError` -- a damaged set never loads as a
        shorter, plausible-looking one."""
        if not isinstance(data, dict):
            raise EpisodeError("demonstration set must be an object")
        if data.get("version") != 1:
            raise EpisodeError(
                f"unsupported demonstration set version: {data.get('version')!r}"
            )
        raw = data.get("episodes")
        if not isinstance(raw, list):
            raise EpisodeError("demonstration set episodes must be a list")
        episodes = [Episode.from_dict(entry) for entry in raw]
        return cls(episodes=episodes)

    # ------------------------------------------------------------ integrity

    def missing_demonstrations(self, demonstration_records: dict) -> list[int]:
        """Episode numbers whose demonstration record is gone.

        An episode pointing at a deleted demonstration is a data
        problem the teacher must see, not a row to drop quietly:
        the episode keeps its snapshot flags and is shown as
        missing its recording."""
        return [
            e.number
            for e in self.episodes
            if e.demonstration_id not in demonstration_records
        ]


# ------------------------------------------------------------ project wiring


def demonstration_set(project) -> DemonstrationSet:
    """Load a project's episode set from its records.

    A project with no set record but a saved demonstration under
    id ``"current"`` (the pre-episode shape) adopts that recording
    as episode 1, in memory; the adoption is saved the next time
    the project saves a set. A corrupt set record raises
    :class:`EpisodeError` -- the caller reports it in plain words
    and the project still opens."""
    record = project.get_record(EPISODES_KIND, EPISODES_RECORD_ID)
    if record is not None:
        return DemonstrationSet.from_dict(record)
    legacy = project.get_record("demonstration", "current")
    if legacy is None:
        return DemonstrationSet()
    return DemonstrationSet(episodes=[_episode_from_legacy(legacy)])


def _episode_from_legacy(demo: dict) -> Episode:
    """Episode 1 from a pre-episode demonstration record: the
    quality flags are read from the record's own measured values
    (the serialised track's measured coverage, the periodic
    measurement where one was recovered)."""
    track = demo.get("track") or {}
    periodic = demo.get("periodic") or {}
    coverage = track.get("coverage_measured")
    if coverage is None:
        coverage = track.get("coverage")
    period = periodic.get("mean_period_s")
    return Episode(
        number=1,
        demonstration_id="current",
        source_name=str(demo.get("source_name", "")),
        tracker=str(demo.get("tracker", "")),
        coverage=(
            float(coverage)
            if isinstance(coverage, (int, float)) and not isinstance(coverage, bool)
            else None
        ),
        period_s=(
            float(period)
            if isinstance(period, (int, float)) and not isinstance(period, bool)
            else None
        ),
        video_sha256=str(demo.get("sha256", "") or ""),
        imported_at=_utc_now(),
    )


def save_demonstration_set(project, episode_set: DemonstrationSet) -> None:
    """Store the set as a project record (the caller saves)."""
    project.put_record(
        EPISODES_KIND, EPISODES_RECORD_ID, episode_set.to_dict()
    )


def new_episode(
    episode_set: DemonstrationSet,
    *,
    source_name: str,
    tracker: str,
    coverage: Optional[float],
    period_s: Optional[float],
    video_sha256: str = "",
) -> Episode:
    """Build the next episode for a set (numbered, unjudged)."""
    number = episode_set.next_number()
    return Episode(
        number=number,
        demonstration_id=episode_record_id(number),
        source_name=source_name,
        tracker=tracker,
        coverage=coverage,
        period_s=period_s,
        video_sha256=video_sha256,
        imported_at=_utc_now(),
    )
