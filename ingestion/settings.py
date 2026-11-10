"""Single source of truth for clip rules used by the LLM prompt, validation and ingestion."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Clip length (seconds). The LLM is asked for the target range; anything outside
# the hard range is rejected during validation.
CLIP_TARGET_MIN_SECONDS = 30
CLIP_TARGET_MAX_SECONDS = 60
CLIP_MIN_SECONDS = 25
CLIP_MAX_SECONDS = 65

# Two candidates sharing at least this many seconds are treated as the same section.
CLIP_OVERLAP_SECONDS = 15

# Most clips kept per song after ranking.
MAX_CLIPS_PER_SONG = 5

# Where fetched/generated transcripts are cached (ignored by git).
TRANSCRIPT_CACHE_DIR = PROJECT_ROOT / "transcript_cache"

# Where audio downloaded for Whisper is stored (*.mp3 is ignored by git).
AUDIO_DIR = PROJECT_ROOT
