import json
import os
import time
from typing import Any

from dotenv import load_dotenv
from groq import Groq

from ingestion.transcript import format_transcript_for_llm

load_dotenv()


def get_groq_client() -> Groq | None:
    """Returns an authenticated Groq client if the API key is configured."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None
    return Groq(api_key=api_key)


def generate_llm_candidates(
    transcript_data: list[dict[str, Any]] | str,
    target_min_seconds: int = 20,
    target_max_seconds: int = 30,
    model_name: str = "openai/gpt-oss-20b",
    max_retries: int = 3,
    initial_retry_delay: float = 2.0,
) -> list[dict[str, Any]]:
    """Analyzes a timestamped song transcript using Groq to select 3-5 candidate discovery sections.

    Token Optimizations:
    - Pre-compacted transcript format.
    - Strict JSON Schema output (no conversational boilerplate tokens).
    - Hard max_tokens ceiling (600 tokens).
    - Exponential backoff retry for TPM/RPM rate limits.
    """
    if isinstance(transcript_data, list):
        if not transcript_data:
            return []
        formatted_transcript = format_transcript_for_llm(transcript_data)
    else:
        formatted_transcript = str(transcript_data).strip()

    if not formatted_transcript:
        return []

    client = get_groq_client()
    if client is None:
        print("Warning: GROQ_API_KEY is not set in environment. Skipping LLM candidate generation.")
        return []

    prompt = f"""You are an expert music curator selecting the best short-form discovery clips from a song.

Analyze the timestamped transcript below and identify 3 to 5 strong, self-contained sections that would work well as music discovery clips.

CLIP SELECTION RULES:
1. Target approximately {target_min_seconds} to {target_max_seconds} seconds per candidate clip.
2. Start where a lyrical or musical section naturally begins (e.g., intro, verse, pre-chorus, chorus/hook, bridge).
3. Do NOT cut off phrases in the middle of a sentence or lyric.
4. Prefer complete musical moments (memorable chorus, hook, emotional peak).
5. start_time and end_time MUST be integers matching transcript timestamps (in seconds).
6. end_time must be strictly greater than start_time.
7. Keep 'reason' extremely concise (under 15 words).
8. Return 3 to 5 candidate clips.

Transcript:
{formatted_transcript}
"""

    for attempt in range(1, max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=600,
                reasoning_format="hidden",
                reasoning_effort="low",
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "clip_selection",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "properties": {
                                "clips": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "start_time": {"type": "integer"},
                                            "end_time": {"type": "integer"},
                                            "reason": {"type": "string"},
                                        },
                                        "required": ["start_time", "end_time", "reason"],
                                        "additionalProperties": False,
                                    },
                                }
                            },
                            "required": ["clips"],
                            "additionalProperties": False,
                        },
                    },
                },
            )

            content = response.choices[0].message.content
            result = json.loads(content)
            clips = result.get("clips", [])

            # Basic schema compliance sanity check
            valid_clips = []
            for clip in clips:
                st = int(clip.get("start_time", 0))
                et = int(clip.get("end_time", 0))
                reason = str(clip.get("reason", "Lyrical candidate"))
                if et > st and st >= 0:
                    valid_clips.append({
                        "start_time": st,
                        "end_time": et,
                        "reason": reason,
                    })

            return valid_clips

        except Exception as e:
            err_str = str(e).lower()
            is_rate_limit = "429" in err_str or "rate limit" in err_str or "tpm" in err_str
            if attempt < max_retries and (is_rate_limit or "connection" in err_str):
                backoff_delay = initial_retry_delay * (2 ** (attempt - 1))
                print(f"Groq API temporary issue ({e}). Retrying in {backoff_delay:.1f}s (Attempt {attempt}/{max_retries})...")
                time.sleep(backoff_delay)
            else:
                print(f"Error generating Groq LLM candidates: {e}")
                return []

    return []


if __name__ == "__main__":
    sample_transcript = """
    [0] Hello darkness my old friend
    [10] I have come to talk with you again
    [25] Because a vision softly creeping
    [45] Left its seeds while I was sleeping
    [70] And the vision that was planted in my brain
    [95] Still remains
    """
    candidates = generate_llm_candidates(sample_transcript)
    print(f"Generated {len(candidates)} candidates:")
    for c in candidates:
        print(f"  [{c['start_time']}s -> {c['end_time']}s]: {c['reason']}")
