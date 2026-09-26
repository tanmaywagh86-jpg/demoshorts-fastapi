import os
import json

from groq import Groq
from dotenv import load_dotenv


load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))


def select_clips(transcript: str) -> list[dict]:

    prompt = f"""
You are selecting the best short-form clips from a song.

Analyze the timestamped transcript below and identify 2 to 3 strong,
self-contained sections that would work well as music discovery clips.

CLIP SELECTION RULES:

1. Do NOT start a clip at an arbitrary or random point.
   Start where the main lyrical or musical section naturally begins.

2. NEVER cut a verse, chorus, hook, bridge, or other coherent section
   in the middle. If a section begins, allow it to complete naturally.

3. Prefer complete musical sections over exact duration.

4. Target approximately 30 to 60 seconds per clip.

5. A clip may be slightly shorter or longer than 30-60 seconds if necessary
   to preserve the complete musical section.

6. Look for:
   - memorable chorus or hook
   - strong lyrical section
   - emotional peak
   - catchy repeated lines
   - natural beginning
   - natural ending
   - sections that make sense when heard independently

7. The beginning must feel intentional.
   Do not start halfway through:
   - a sentence
   - a lyric phrase
   - a verse
   - a chorus
   - a musical section

8. The ending must also feel natural.
   Do not stop halfway through a lyrical or musical phrase.

9. Prefer a complete verse + chorus, complete chorus/hook,
   or another naturally complete musical unit.

10. Do NOT combine unrelated parts of the song just to reach 30-60 seconds.

11. If the best section is slightly outside 30-60 seconds, preserve
    the natural musical structure instead of forcibly cutting it.

12. start_time must correspond to a timestamp present in the transcript.

13. end_time must correspond to a timestamp present in the transcript.

14. Do not invent timestamps.

15. Select the strongest sections rather than simply selecting
    the first sections in the song.

16. Each selected clip should feel like a self-contained musical moment
    that a listener can start listening to naturally.

Return 2 to 3 clips.atleast of 30 secs

Transcript:

{transcript}
"""

    response = client.chat.completions.create(
        model="openai/gpt-oss-20b",

        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ],

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
                                    "start_time": {
                                        "type": "integer"
                                    },
                                    "end_time": {
                                        "type": "integer"
                                    },
                                    "reason": {
                                        "type": "string"
                                    }
                                },
                                "required": [
                                    "start_time",
                                    "end_time",
                                    "reason"
                                ],
                                "additionalProperties": False
                            }
                        }
                    },
                    "required": [
                        "clips"
                    ],
                    "additionalProperties": False
                }
            }
        }
    )

    result = json.loads(
        response.choices[0].message.content
    )

    return result["clips"]


if __name__ == "__main__":

    transcript_file = "mWRsgZuwf_8_transcript.txt"

    with open(transcript_file, "r", encoding="utf-8") as f:
        transcript = f.read()

    clips = select_clips(transcript)

    print("\nSelected clips:\n")

    for i, clip in enumerate(clips, start=1):

        print(f"Clip {i}")
        print(f"Start  : {clip['start_time']} seconds")
        print(f"End    : {clip['end_time']} seconds")
        print(f"Reason : {clip['reason']}")
        print()