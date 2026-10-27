from typing import Any


def validate_candidate(
    candidate: dict[str, Any],
    song_duration: float | None = None,
    min_duration: int = 15,
    max_duration: int = 35,
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


def merge_and_deduplicate_candidates(
    groq_candidates: list[dict[str, Any]] | None = None,
    audio_candidates: list[dict[str, Any]] | None = None,
    song_duration: float | None = None,
    min_duration: int = 15,
    max_duration: int = 35,
    overlap_threshold_seconds: int = 12,
    iou_threshold: float = 0.45,
) -> list[dict[str, Any]]:
    """Combines lyrical Groq candidates and acoustic librosa candidates into a single deduplicated candidate pool.

    - Validates candidate bounds.
    - Tags candidates with source: 'groq', 'audio', or 'both'.
    - Merges substantially overlapping sections intelligently.
    - Returns sorted list: [{'start_time': int, 'end_time': int, 'source': str, 'reason': str}]
    """
    pool: list[dict[str, Any]] = []

    # Tag and collect Groq candidates
    if groq_candidates:
        for c in groq_candidates:
            cand = {
                "start_time": int(c["start_time"]),
                "end_time": int(c["end_time"]),
                "source": c.get("source", "groq"),
                "reason": c.get("reason", "Lyrical/thematic section selected by Groq"),
            }
            if validate_candidate(cand, song_duration, min_duration, max_duration):
                pool.append(cand)

    # Tag and collect Audio candidates
    if audio_candidates:
        for c in audio_candidates:
            cand = {
                "start_time": int(c["start_time"]),
                "end_time": int(c["end_time"]),
                "source": c.get("source", "audio"),
                "reason": c.get("reason", "High-energy audio region identified by librosa"),
            }
            if validate_candidate(cand, song_duration, min_duration, max_duration):
                pool.append(cand)

    if not pool:
        return []

    # Sort by start_time
    pool.sort(key=lambda x: (x["start_time"], x["end_time"]))

    merged: list[dict[str, Any]] = []

    for cand in pool:
        if not merged:
            merged.append(cand)
            continue

        last = merged[-1]

        # Calculate overlap duration and IoU
        overlap = max(0, min(last["end_time"], cand["end_time"]) - max(last["start_time"], cand["start_time"]))
        union = max(last["end_time"], cand["end_time"]) - min(last["start_time"], cand["start_time"])
        iou = overlap / union if union > 0 else 0.0

        is_overlapping = overlap >= overlap_threshold_seconds or iou >= iou_threshold

        if is_overlapping:
            # Determine combined source
            sources = set()
            for s in (last.get("source", ""), cand.get("source", "")):
                if s == "both":
                    sources.add("groq")
                    sources.add("audio")
                elif s in ("groq", "audio"):
                    sources.add(s)

            combined_source = "both" if len(sources) > 1 else (next(iter(sources)) if sources else "groq")

            # Determine best start and end times
            # If one is from audio, audio beat refinement is often tighter on start/end
            if cand.get("source") == "audio" and last.get("source") == "groq":
                best_start = cand["start_time"]
                best_end = cand["end_time"]
                best_reason = f"{last['reason']} (aligned with high-energy audio peak)"
            elif last.get("source") == "audio" and cand.get("source") == "groq":
                best_start = last["start_time"]
                best_end = last["end_time"]
                best_reason = f"{cand['reason']} (aligned with high-energy audio peak)"
            else:
                # Merge bounds, keeping duration within target max_duration
                best_start = min(last["start_time"], cand["start_time"])
                best_end = min(best_start + max_duration, max(last["end_time"], cand["end_time"]))
                best_reason = f"{last['reason']} | {cand['reason']}" if last["reason"] != cand["reason"] else last["reason"]

            merged[-1] = {
                "start_time": best_start,
                "end_time": best_end,
                "source": combined_source,
                "reason": best_reason,
            }
        else:
            merged.append(cand)

    # Final pass: clamp end_time if song_duration is given
    if song_duration is not None and song_duration > 0:
        for item in merged:
            if item["end_time"] > int(round(song_duration)):
                item["end_time"] = int(round(song_duration))

    return merged
