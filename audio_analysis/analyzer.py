import subprocess
from pathlib import Path

import librosa
import numpy as np
import matplotlib.pyplot as plt

from clip_selection.selector import select_clips
from database import SessionLocal
from models import Clip, Song


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def convert_to_wav(audio_path):

    audio_path = Path(audio_path)
    wav_path = audio_path.with_suffix(".wav")

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(audio_path),
            "-ac",
            "1",
            "-ar",
            "22050",
            str(wav_path)
        ],
        check=True
    )

    return str(wav_path)


def load_audio_for_analysis(audio_path):
    wav_path = convert_to_wav(audio_path)

    y, sr = librosa.load(
        wav_path,
        sr=None,
        mono=True
    )

    return y, sr


def analyze_energy(audio_path):

    y, sr = load_audio_for_analysis(audio_path)

    rms = librosa.feature.rms(
        y=y,
        frame_length=2048,
        hop_length=512
    )[0]

    times = librosa.frames_to_time(
        np.arange(len(rms)),
        sr=sr,
        hop_length=512
    )

    return times, rms


def detect_beats(audio_path):

    y, sr = load_audio_for_analysis(audio_path)

    tempo, beat_frames = librosa.beat.beat_track(
        y=y,
        sr=sr
    )

    tempo = float(np.asarray(tempo).item())

    beat_times = librosa.frames_to_time(
        beat_frames,
        sr=sr
    )

    return tempo, beat_times


def refine_boundaries(start_time, end_time, beat_times):

    search_window = 2.0
    min_duration = 30.0
    max_duration = 60.0
    duration_tolerance = 2.0

    beats = np.asarray(beat_times)

    if len(beats) == 0:
        return start_time, end_time

    start_candidates = beats[
        (beats >= start_time - search_window)
        & (beats <= start_time + search_window)
    ]

    end_candidates = beats[
        (beats >= end_time - search_window)
        & (beats <= end_time + search_window)
    ]

    if len(start_candidates) > 0:
        earlier_start_beats = start_candidates[
            start_candidates <= start_time
        ]

        if len(earlier_start_beats) > 0:
            refined_start = float(earlier_start_beats[-1])
        else:
            refined_start = float(start_candidates[0])
    else:
        refined_start = start_time

    if len(end_candidates) > 0:
        later_end_beats = end_candidates[
            end_candidates >= end_time
        ]

        if len(later_end_beats) > 0:
            refined_end = float(later_end_beats[0])
        else:
            refined_end = float(end_candidates[-1])
    else:
        refined_end = end_time

    if refined_start >= refined_end:
        return start_time, end_time

    refined_duration = refined_end - refined_start

    if refined_duration > max_duration + duration_tolerance:
        latest_allowed_end = refined_start + max_duration + duration_tolerance
        target_end = refined_start + max_duration

        end_options = beats[
            (beats >= refined_start + min_duration)
            & (beats <= latest_allowed_end)
        ]

        if len(end_options) > 0:
            refined_end = float(
                end_options[
                    np.argmin(np.abs(end_options - target_end))
                ]
            )

        else:
            earliest_allowed_start = refined_end - max_duration - duration_tolerance
            target_start = refined_end - max_duration

            start_options = beats[
                (beats >= earliest_allowed_start)
                & (beats <= refined_end - min_duration)
            ]

            if len(start_options) > 0:
                refined_start = float(
                    start_options[
                        np.argmin(np.abs(start_options - target_start))
                    ]
                )

    if refined_start >= refined_end:
        return start_time, end_time

    return round(refined_start, 2), round(refined_end, 2)


def score_candidate(start_time, end_time, times, rms):

    mask = (times >= start_time) & (times <= end_time)

    candidate_times = times[mask]
    candidate_rms = rms[mask]

    if len(candidate_rms) == 0:
        return None

    average_energy = float(np.mean(candidate_rms))

    peak_energy = float(np.max(candidate_rms))

    peak_index = np.argmax(candidate_rms)

    peak_time = float(candidate_times[peak_index])

    return {
        "start_time": start_time,
        "end_time": end_time,
        "average_energy": round(average_energy, 4),
        "peak_energy": round(peak_energy, 4),
        "peak_time": round(peak_time, 2)
    }


def analyze_candidates(clips, times, rms):

    results = []

    for clip in clips:

        result = score_candidate(
            clip["start_time"],
            clip["end_time"],
            times,
            rms
        )

        if result is not None:

            # Keep Groq's reason
            result["reason"] = clip.get(
                "reason",
                ""
            )

            results.append(result)

    return results


def save_refined_clips(youtube_id, refined_clips):

    db = SessionLocal()

    try:
        song = (
            db.query(Song)
            .filter(Song.youtube_id == youtube_id)
            .first()
        )

        if song is None:
            song = Song(
                title=youtube_id,
                artist="Unknown",
                youtube_id=youtube_id,
                genre=None
            )

            db.add(song)
            db.flush()

        saved_count = 0

        for clip in refined_clips:
            start_time = int(round(clip["refined_start_time"]))
            end_time = int(round(clip["refined_end_time"]))

            existing_clip = (
                db.query(Clip)
                .filter(
                    Clip.song_id == song.id,
                    Clip.start_time == start_time,
                    Clip.end_time == end_time
                )
                .first()
            )

            if existing_clip is not None:
                continue

            db.add(
                Clip(
                    song_id=song.id,
                    start_time=start_time,
                    end_time=end_time
                )
            )

            saved_count += 1

        db.commit()

        total_clips = (
            db.query(Clip)
            .filter(Clip.song_id == song.id)
            .count()
        )

        return {
            "song_id": song.id,
            "saved_count": saved_count,
            "total_clips": total_clips
        }

    finally:
        db.close()


def get_storage_counts(youtube_id):

    db = SessionLocal()

    try:
        song = (
            db.query(Song)
            .filter(Song.youtube_id == youtube_id)
            .first()
        )

        if song is None:
            return {
                "song_exists": False,
                "songs": 0,
                "clips": 0
            }

        clips = (
            db.query(Clip)
            .filter(Clip.song_id == song.id)
            .count()
        )

        return {
            "song_exists": True,
            "songs": 1,
            "clips": clips
        }

    finally:
        db.close()


if __name__ == "__main__":

    # --------------------------------
    # 1. Find audio
    # --------------------------------

    audio_files = list(PROJECT_ROOT.glob("*.mp3"))

    if not audio_files:
        print("ERROR: No MP3 files found.")
        exit()

    audio_file = audio_files[0]

    print(f"Using audio: {audio_file}")


    # --------------------------------
    # 2. Analyze audio
    # --------------------------------

    times, rms = analyze_energy(audio_file)

    print(f"\nAudio frames: {len(rms)}")
    print(f"Audio duration: {times[-1]:.2f} seconds")


    # --------------------------------
    # 3. Detect beats
    # --------------------------------

    tempo, beat_times = detect_beats(audio_file)

    print(f"\nEstimated BPM: {float(tempo):.2f}")
    print("First 20 detected beat timestamps:")

    for beat_time in beat_times[:20]:

        print(f"{beat_time:.2f}s")


    # --------------------------------
    # 4. Get transcript
    # --------------------------------

    transcript_files = list(
        PROJECT_ROOT.glob("*_transcript.txt")
    )

    if not transcript_files:

        print("ERROR: No transcript file found.")
        exit()

    transcript_file = transcript_files[0]

    print(f"\nUsing transcript: {transcript_file}")


    with open(
        transcript_file,
        "r",
        encoding="utf-8"
    ) as f:

        transcript = f.read()


    # --------------------------------
    # 5. Groq selects candidates
    # --------------------------------

    print("\nAsking Groq to select clips...")

    clips = select_clips(transcript)

    print("\nGroq candidates:\n")

    for i, clip in enumerate(clips, start=1):

        print(
            f"Clip {i}: "
            f"{clip['start_time']}s -> "
            f"{clip['end_time']}s"
        )

        print(
            f"Reason: {clip['reason']}\n"
        )


    # --------------------------------
    # 6. Refine candidate boundaries
    # --------------------------------

    refined_clips = []

    print("\nBeat-refined boundaries:\n")

    for i, clip in enumerate(clips, start=1):

        original_start = clip["start_time"]
        original_end = clip["end_time"]

        refined_start, refined_end = refine_boundaries(
            original_start,
            original_end,
            beat_times
        )

        refined_clip = {
            **clip,
            "refined_start_time": refined_start,
            "refined_end_time": refined_end
        }

        refined_clips.append(refined_clip)

        original_duration = original_end - original_start
        refined_duration = refined_end - refined_start

        print(f"Clip {i}")
        print(
            f"Original: {original_start}s -> {original_end}s "
            f"({original_duration:.2f}s)"
        )
        print(
            f"Refined: {refined_start:.2f}s -> {refined_end:.2f}s "
            f"({refined_duration:.2f}s)"
        )
        print()


    # --------------------------------
    # 7. Store refined clips
    # --------------------------------

    youtube_id = audio_file.stem

    first_storage_result = save_refined_clips(
        youtube_id,
        refined_clips
    )

    second_storage_result = save_refined_clips(
        youtube_id,
        refined_clips
    )

    storage_counts = get_storage_counts(youtube_id)

    print("\nPostgreSQL storage:\n")
    print(f"Song exists: {storage_counts['song_exists']}")
    print(
        f"First storage saved clips: "
        f"{first_storage_result['saved_count']}"
    )
    print(
        f"Second storage saved clips: "
        f"{second_storage_result['saved_count']}"
    )
    print(
        f"Stored songs for current YouTube ID: "
        f"{storage_counts['songs']}"
    )
    print(
        f"Stored clips for current song: "
        f"{storage_counts['clips']}"
    )


    # --------------------------------
    # 8. Score candidates using audio
    # --------------------------------

    scored_clips = analyze_candidates(
        clips,
        times,
        rms
    )


    print("\nAudio analysis:\n")

    for i, clip in enumerate(
        scored_clips,
        start=1
    ):

        print(f"Clip {i}")

        print(
            f"Start: {clip['start_time']}s"
        )

        print(
            f"End: {clip['end_time']}s"
        )

        print(
            f"Average energy: "
            f"{clip['average_energy']}"
        )

        print(
            f"Peak energy: "
            f"{clip['peak_energy']}"
        )

        print(
            f"Peak time: "
            f"{clip['peak_time']}s"
        )

        print(
            f"Reason: {clip['reason']}"
        )

        print()
