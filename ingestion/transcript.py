from youtube_transcript_api import YouTubeTranscriptApi
import subprocess
from faster_whisper import WhisperModel


# --------------------------------------------------
# 1. Try to get transcript from YouTube captions
# --------------------------------------------------

def get_timestamped_transcript(youtube_id: str) -> list[dict]:
    try:
        ytt_api = YouTubeTranscriptApi()

        transcript_list = ytt_api.list(youtube_id)

        # Take the first available transcript
        transcript = next(iter(transcript_list))

        print(
            f"Using YouTube transcript: "
            f"{transcript.language} ({transcript.language_code})"
        )

        fetched = transcript.fetch()

        return fetched.to_raw_data()

    except Exception as e:
        print(f"Error fetching transcript for {youtube_id}: {e}")
        return []


# --------------------------------------------------
# 2. Format transcript for Groq / LLM
# --------------------------------------------------

def format_transcript_for_llm(transcript_data: list[dict]) -> str:
    formatted_lines = []

    for entry in transcript_data:
        start_time = int(entry["start"])
        text = entry["text"].strip()

        formatted_lines.append(f"[{start_time}] {text}")

    return "\n".join(formatted_lines)


# --------------------------------------------------
# 3. Whisper fallback
# --------------------------------------------------

def transcribe_with_whisper(youtube_id: str) -> list[dict]:

    print("Loading Whisper model...")

    whisper_model = WhisperModel(
    "base",
    device="cpu",
    compute_type="int8",
    cpu_threads=4,
    num_workers=1
)

    audio_path = f"{youtube_id}.mp3"

    # Download audio from YouTube
    subprocess.run(
        [
            "yt-dlp",
            "-x",
            "--audio-format", "mp3",
            "-o", f"{youtube_id}.%(ext)s",
            f"https://www.youtube.com/watch?v={youtube_id}"
        ],
        check=True
    )

    # Transcribe audio
    segments, info = whisper_model.transcribe(audio_path)

    print(f"Whisper detected language: {info.language}")

    return [
        {
            "start": segment.start,
            "duration": segment.end - segment.start,
            "text": segment.text.strip()
        }
        for segment in segments
    ]


# --------------------------------------------------
# 4. Main transcript function
# --------------------------------------------------

def get_transcript_with_fallback(youtube_id: str) -> list[dict]:

    # First try YouTube captions
    data = get_timestamped_transcript(youtube_id)

    if data:
        print("Using YouTube transcript.")
        return data

    # If captions unavailable, use Whisper
    print("YouTube transcript unavailable.")
    print("Falling back to Whisper...")

    return transcribe_with_whisper(youtube_id)


# --------------------------------------------------
# 5. Test
# --------------------------------------------------

if __name__ == "__main__":

    test_id = "-8C_2BBVWk8"

    raw_data = get_transcript_with_fallback(test_id)

    if raw_data:

        print("\nTranscript fetched successfully!")

        print(f"Entries: {len(raw_data)}")

        last = raw_data[-1]

        print(
            f"Last entry starts at "
            f"{last['start']:.0f}s, "
            f"duration {last['duration']:.1f}s"
        )

        full_text = format_transcript_for_llm(raw_data)

        print(f"Total characters: {len(full_text)}")

        # Preview the end
        print("\n--- END OF TRANSCRIPT ---")
        print(full_text[-500:])

        # Save complete transcript
        with open(
            f"{test_id}_transcript.txt",
            "w",
            encoding="utf-8"
        ) as f:
            f.write(full_text)

        print(
            f"\nFull transcript saved to "
            f"{test_id}_transcript.txt"
        )

    else:
        print("No transcript was returned.")