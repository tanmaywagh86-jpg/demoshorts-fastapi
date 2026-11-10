from typing import Any, Callable

from ingestion.settings import CLIP_MAX_SECONDS, CLIP_MIN_SECONDS, CLIP_OVERLAP_SECONDS

# Lower number = kept first when a song has more candidates than the cap.
SOURCE_PRIORITY = {"both": 0, "groq": 1, "audio": 2}


def validate_candidate(
    candidate: dict[str, Any],
    song_duration: float | None = None,
    min_duration: int = CLIP_MIN_SECONDS,
    max_duration: int = CLIP_MAX_SECONDS,
) -> bool:
    """Validates that a candidate clip has valid, positive timestamps and a reasonable duration."""
    try:
        start_time = int(candidate.get("start_time", -1))
        end_time = int(candidate.get("end_time", -1))
    except (ValueError, TypeError):
        return False

    if start_time < 0 or end_time <= start_time:
        return False

    duration = end_time - start_time
    if duration < min_duration or duration > max_duration:
        return False

    if song_duration is not None and song_duration > 0:
        if start_time >= song_duration:
            return False

    return True


def _overlaps(
    a: dict[str, Any],
    b: dict[str, Any],
    overlap_threshold_seconds: int,
    iou_threshold: float,
) -> bool:
    overlap = max(0, min(a["end_time"], b["end_time"]) - max(a["start_time"], b["start_time"]))
    union = max(a["end_time"], b["end_time"]) - min(a["start_time"], b["start_time"])
    iou = overlap / union if union > 0 else 0.0
    return overlap >= overlap_threshold_seconds or iou >= iou_threshold


def merge_and_deduplicate_candidates(
    groq_candidates: list[dict[str, Any]] | None = None,
    audio_candidates: list[dict[str, Any]] | None = None,
    song_duration: float | None = None,
    min_duration: int = CLIP_MIN_SECONDS,
    max_duration: int = CLIP_MAX_SECONDS,
    overlap_threshold_seconds: int = CLIP_OVERLAP_SECONDS,
    iou_threshold: float = 0.45,
    energy_fn: Callable[[int, int], float | None] | None = None,
    max_clips: int | None = None,
) -> list[dict[str, Any]]:
    """Combines lyrical (Groq) and acoustic (librosa) candidates into one deduplicated list.

    Lyrics decide the boundaries: when a Groq candidate and an audio window cover the
    same section, the Groq start/end are kept (they follow lyric lines, so the clip
    does not cut a phrase) and the candidate is tagged source='both'. Audio windows
    that match no Groq candidate are kept as source='audio'.

    energy_fn(start, end), when given, adds an 'energy' value used only for ranking.
    max_clips, when given, keeps the best candidates: 'both' first, then 'groq',
    then 'audio', higher energy first within each group.

    Returns a chronological list of
    {'start_time': int, 'end_time': int, 'source': str, 'reason': str[, 'energy': float]}.
    """

    def collect(candidates, default_source, default_reason):
        collected = []
        for c in sorted(candidates or [], key=lambda x: (int(x["start_time"]), int(x["end_time"]))):
            cand = {
                "start_time": int(c["start_time"]),
                "end_time": int(c["end_time"]),
                "source": c.get("source", default_source),
                "reason": c.get("reason", default_reason),
            }
            if not validate_candidate(cand, song_duration, min_duration, max_duration):
                continue
            if any(_overlaps(cand, kept, overlap_threshold_seconds, iou_threshold) for kept in collected):
                continue  # duplicate of an earlier candidate from the same source
            collected.append(cand)
        return collected

    kept = collect(groq_candidates, "groq", "Lyrical/thematic section selected by Groq")
    audio = collect(audio_candidates, "audio", "High-energy audio region identified by librosa")

    for window in audio:
        match = next(
            (k for k in kept if _overlaps(window, k, overlap_threshold_seconds, iou_threshold)),
            None,
        )
        if match is None:
            kept.append(window)
        elif match["source"] == "groq":
            match["source"] = "both"
            match["reason"] = f"{match['reason']} (matches a high-energy section)"

    # Clamp to the end of the song when its length is known.
    if song_duration is not None and song_duration > 0:
        last_second = int(round(song_duration))
        for item in kept:
            item["end_time"] = min(item["end_time"], last_second)
        kept = [item for item in kept if item["end_time"] > item["start_time"]]

    if energy_fn is not None:
        for item in kept:
            energy = energy_fn(item["start_time"], item["end_time"])
            if energy is not None:
                item["energy"] = energy

    if max_clips is not None and len(kept) > max_clips:
        kept.sort(
            key=lambda c: (SOURCE_PRIORITY.get(c["source"], 3), -c.get("energy", 0.0))
        )
        kept = kept[:max_clips]

    kept.sort(key=lambda c: (c["start_time"], c["end_time"]))
    return kept
