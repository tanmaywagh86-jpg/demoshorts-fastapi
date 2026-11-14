import argparse
import csv
import sys
import time
from pathlib import Path
from typing import Any

from ingestion.ingest_song import ingest_song


def parse_batch_file(file_path: str | Path) -> list[dict[str, Any]]:
    """Parses a CSV or text file containing song entries to ingest.

    CSV format supports header columns (case-insensitive):
      - url (or youtube_url, youtube_id, link) [Required]
      - title [Optional]
      - artist [Optional]
      - genre [Optional]
      - audio_path (or audio) [Optional]

    Text format (.txt) supports one URL or video ID per line (empty lines and # comments ignored).
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Batch file not found: {path}")

    entries = []

    if path.suffix.lower() == ".csv":
        with open(path, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return []

            # Normalize column names to lowercase stripped
            field_map = {fn.strip().lower(): fn for fn in reader.fieldnames if fn}

            url_key = None
            for candidate in ("url", "youtube_url", "youtube_id", "link", "video_id"):
                if candidate in field_map:
                    url_key = field_map[candidate]
                    break

            if not url_key:
                raise ValueError(
                    f"CSV must contain a 'url', 'youtube_url', or 'youtube_id' column. Found columns: {reader.fieldnames}"
                )

            title_key = field_map.get("title")
            artist_key = field_map.get("artist")
            genre_key = field_map.get("genre")
            audio_key = field_map.get("audio_path") or field_map.get("audio")

            for row in reader:
                url_val = (row.get(url_key) or "").strip()
                if not url_val:
                    continue

                entries.append({
                    "url": url_val,
                    "title": (row.get(title_key) or "").strip() or None if title_key else None,
                    "artist": (row.get(artist_key) or "").strip() or None if artist_key else None,
                    "genre": (row.get(genre_key) or "").strip() or None if genre_key else None,
                    "audio_path": (row.get(audio_key) or "").strip() or None if audio_key else None,
                })
    else:
        # Plain text file (one URL / video ID per line)
        with open(path, mode="r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                entries.append({
                    "url": line,
                    "title": None,
                    "artist": None,
                    "genre": None,
                    "audio_path": None,
                })

    return entries


def batch_ingest_songs(
    entries: list[dict[str, Any]],
    force_reprocess: bool = False,
    use_whisper: bool = True,
    delay_between_requests: float = 1.0,
    db: Any = None,
) -> dict[str, Any]:
    """Processes a list of song entries sequentially with polite rate-limiting and error reporting."""
    total = len(entries)
    succeeded = 0
    failed = 0
    total_clips = 0
    results = []
    errors = []

    print(f"\n==================================================")
    print(f"Starting batch ingestion of {total} song(s)...")
    print(f"==================================================")

    for index, entry in enumerate(entries, start=1):
        url = entry["url"]
        title = entry.get("title")
        artist = entry.get("artist")
        genre = entry.get("genre")
        audio_path = entry.get("audio_path")

        print(f"\n[{index}/{total}] Processing: {url}")
        if title or artist:
            print(f"       Metadata: '{title or '?'}' by '{artist or '?'}'")

        try:
            summary = ingest_song(
                youtube_url_or_id=url,
                title=title,
                artist=artist,
                genre=genre,
                audio_path=audio_path,
                force_reprocess=force_reprocess,
                use_whisper=use_whisper,
                db=db,
            )
            succeeded += 1
            clip_count = len(summary.get("clips", []))
            total_clips += clip_count
            results.append(summary)
            print(f"       Success: {summary['title']} -> {clip_count} clip(s)")

        except Exception as err:
            failed += 1
            err_msg = str(err)
            errors.append({"url": url, "error": err_msg})
            print(f"       Failed: {err_msg}")

        if delay_between_requests > 0 and index < total:
            time.sleep(delay_between_requests)

    summary_report = {
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
        "total_clips": total_clips,
        "results": results,
        "errors": errors,
    }

    print(f"\n==================================================")
    print(f"Batch Ingestion Complete:")
    print(f"  Total items:    {total}")
    print(f"  Succeeded:      {succeeded}")
    print(f"  Failed:         {failed}")
    print(f"  Clips ingested: {total_clips}")
    if errors:
        print(f"\nFailures:")
        for err in errors:
            print(f"  - {err['url']}: {err['error']}")
    print(f"==================================================\n")

    return summary_report


def main():
    parser = argparse.ArgumentParser(
        description="Batch Ingestion Utility for Songs & Candidate Clips"
    )
    parser.add_argument(
        "file",
        help="Path to CSV file (with 'url' column) or TXT file (one URL per line)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay in seconds between processing songs to respect rate limits (default: 1.0)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-running analysis even if song already exists in DB",
    )
    parser.add_argument(
        "--no-whisper",
        action="store_true",
        help="Do not download audio and run Whisper when YouTube captions are unavailable",
    )

    args = parser.parse_args()

    try:
        entries = parse_batch_file(args.file)
        if not entries:
            print(f"No valid song entries found in '{args.file}'.")
            sys.exit(0)

        report = batch_ingest_songs(
            entries=entries,
            force_reprocess=args.force,
            use_whisper=not args.no_whisper,
            delay_between_requests=args.delay,
        )

        if report["failed"] > 0 and report["succeeded"] == 0:
            sys.exit(1)

    except Exception as exc:
        print(f"Batch execution error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
