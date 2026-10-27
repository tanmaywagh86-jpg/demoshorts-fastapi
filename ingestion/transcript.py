import re
import subprocess
from urllib.parse import parse_qs, urlparse

from faster_whisper import WhisperModel
from youtube_transcript_api import YouTubeTranscriptApi


# --------------------------------------------------
# 0. Extract YouTube video ID
# --------------------------------------------------

def extract_video_id(url_or_id: str) -> str:
    """Extracts an 11-character YouTube video ID from a URL or raw ID string."""
    if not url_or_id or not isinstance(url_or_id, str):
        return ""

    url_or_id = url_or_id.strip()

    # If it's already an exact 11-character alphanumeric/dash/underscore ID
    if re.fullmatch(r"[a-zA-Z0-9_-]{11}", url_or_id):
        return url_or_id

    try:
        parsed = urlparse(url_or_id)
        if parsed.hostname in ("www.youtube.com", "youtube.com", "m.youtube.com"):
            if parsed.path == "/watch":
                qs = parse_qs(parsed.query)
                if "v" in qs and qs["v"]:
                    return qs["v"][0]
            elif parsed.path.startswith(("/embed/", "/v/", "/shorts/")):
                parts = parsed.path.strip("/").split("/")
                if len(parts) >= 2:
                    return parts[1]
        elif parsed.hostname == "youtu.be":
            return parsed.path.strip("/").split("?")[0]
    except Exception:
        pass

    # Regex fallback for standard 11-character YouTube ID patterns
    match = re.search(
        r"(?:v=|\/embed\/|\/shorts\/|youtu\.be\/|\/v\/)([a-zA-Z0-9_-]{11})",
        url_or_id,
    )
    if match:
        return match.group(1)

    return url_or_id


# --------------------------------------------------
# 1. Try to get transcript from YouTube captions & Local Cache
# --------------------------------------------------

def load_cached_transcript(video_id: str) -> list[dict]:
    """Loads a locally cached transcript file if available (e.g., {video_id}_transcript.txt)."""
    if not video_id:
        return []
    
    cache_path = f"{video_id}_transcript.txt"
    try:
        import os
        if os.path.exists(cache_path):
            entries = []
            with open(cache_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    match = re.match(r"^\[(\d+(?:\.\d+)?)\]\s*(.+)$", line)
                    if match:
                        start_sec = float(match.group(1))
                        text = match.group(2).strip()
                        if text:
                            entries.append({"start": start_sec, "duration": 2.0, "text": text})
            if entries:
                return entries
    except Exception:
        pass
    return []


def save_cached_transcript(video_id: str, formatted_transcript: str) -> None:
    """Saves formatted transcript to a local cache file for token and network savings."""
    if not video_id or not formatted_transcript:
        return
    cache_path = f"{video_id}_transcript.txt"
    try:
        import os
        if not os.path.exists(cache_path):
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(formatted_transcript)
    except Exception:
        pass


def get_timestamped_transcript(url_or_id: str) -> list[dict]:
    """Fetches timestamped captions for a YouTube video.

    First checks local cache, then YouTube captions.
    Returns a list of dicts with keys: 'start', 'duration', 'text'.
    Returns an empty list gracefully if captions are not available.
    """
    video_id = extract_video_id(url_or_id)
    if not video_id:
        return []

    # Check local cache first (saves network & Whisper calls)
    cached = load_cached_transcript(video_id)
    if cached:
        return cached

    try:
        ytt_api = YouTubeTranscriptApi()
        transcript_list = ytt_api.list(video_id)

        # Take the first available transcript (preferring user's or manual/auto)
        transcript = next(iter(transcript_list))
        fetched = transcript.fetch()
        raw_data = fetched.to_raw_data()

        # Standardize structure
        standardized = []
        for entry in raw_data:
            standardized.append({
                "start": float(entry.get("start", 0.0)),
                "duration": float(entry.get("duration", 0.0)),
                "text": str(entry.get("text", "")).strip(),
            })

        return standardized

    except Exception as e:
        print(f"Info: Could not retrieve YouTube captions for {video_id}: {e}")
        return []


# --------------------------------------------------
# 2. Format transcript for Groq / LLM (Token Optimized)
# --------------------------------------------------

NOISE_PATTERNS = re.compile(
    r"^\[(music|applause|laughter|cheering|instrumental|sound)\]$|^[\(\[].*?(music|applause).*?[\)\]]$|^[♪♫\s]+$",
    re.IGNORECASE,
)


def format_transcript_for_llm(transcript_data: list[dict]) -> str:
    """Formats timestamped transcript entries into '[seconds] text' lines.

    Token Optimizations:
    - Filters non-lyrical markers ([Music], [Applause], ♪ symbols).
    - Compacts timestamp precision to integer seconds.
    - Merges consecutive entries within 2 seconds to reduce timestamp overhead.
    """
    cleaned_entries: list[tuple[int, str]] = []

    for entry in transcript_data:
        text = str(entry.get("text", "")).strip()
        if not text or NOISE_PATTERNS.match(text):
            continue

        start_time = int(round(float(entry.get("start", 0))))
        cleaned_entries.append((start_time, text))

    if not cleaned_entries:
        return ""

    # Merge consecutive entries occurring close together (< 2s)
    merged_lines: list[str] = []
    curr_start, curr_text = cleaned_entries[0]

    for next_start, next_text in cleaned_entries[1:]:
        if next_start - curr_start <= 2:
            curr_text = f"{curr_text} {next_text}"
        else:
            merged_lines.append(f"[{curr_start}] {curr_text}")
            curr_start, curr_text = next_start, next_text

    merged_lines.append(f"[{curr_start}] {curr_text}")
    return "\n".join(merged_lines)


# --------------------------------------------------
# 3. Whisper fallback
# --------------------------------------------------

def transcribe_with_whisper(url_or_id: str) -> list[dict]:
    """Transcribes downloaded audio using faster-whisper as a fallback."""
    video_id = extract_video_id(url_or_id)
    audio_path = f"{video_id}.mp3"

    print(f"Running Whisper transcription for {video_id}...")

    try:
        # Download audio from YouTube
        subprocess.run(
            [
                "yt-dlp",
                "-x",
                "--audio-format", "mp3",
                "-o", f"{video_id}.%(ext)s",
                f"https://www.youtube.com/watch?v={video_id}",
            ],
            check=True,
            capture_output=True,
        )

        whisper_model = WhisperModel(
            "base",
            device="cpu",
            compute_type="int8",
            cpu_threads=4,
            num_workers=1,
        )

        segments, _info = whisper_model.transcribe(audio_path)

        return [
            {
                "start": float(segment.start),
                "duration": float(segment.end - segment.start),
                "text": segment.text.strip(),
            }
            for segment in segments
        ]
    except Exception as e:
        print(f"Whisper fallback failed for {video_id}: {e}")
        return []


# --------------------------------------------------
# 4. Main transcript function
# --------------------------------------------------

def get_transcript_with_fallback(url_or_id: str) -> list[dict]:
    """First attempts to fetch YouTube captions; falls back to Whisper if unavailable."""
    data = get_timestamped_transcript(url_or_id)
    if data:
        return data

    print("YouTube transcript unavailable. Falling back to Whisper...")
    whisper_data = transcribe_with_whisper(url_or_id)
    if whisper_data:
        video_id = extract_video_id(url_or_id)
        save_cached_transcript(video_id, format_transcript_for_llm(whisper_data))
    return whisper_data


if __name__ == "__main__":
    test_url = "https://www.youtube.com/watch?v=-8C_2BBVWk8"
    video_id = extract_video_id(test_url)
    print(f"Extracted video ID: {video_id}")
    raw_data = get_timestamped_transcript(video_id)
    print(f"Fetched {len(raw_data)} transcript lines.")