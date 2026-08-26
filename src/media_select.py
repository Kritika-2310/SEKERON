import argparse
import json
import subprocess
from pathlib import Path

MAX_IMAGES = 6
MAX_AUDIO = 3
MAX_AUDIO_WINDOW_SEC = 45
MAX_VIDEOS = 4
MAX_FRAMES_PER_VIDEO = 5
FRAME_INTERVAL_SEC = 8


def evenly_spaced_indices(n_total: int, n_take: int):
    if n_total <= n_take:
        return list(range(n_total))
    step = n_total / n_take
    return sorted({int(i * step) for i in range(n_take)})


def get_video_duration(path: Path):
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        return float(out.stdout.strip())
    except Exception:
        return None


def select_for_artist(record: dict, data_dir: Path) -> dict:
    artist_dir = data_dir / (
        "photographers" if record["category"] == "photographer" else
        "musicians" if record["category"] == "musician" else
        "video_editors"
    ) / record["artist_id"]

    images = [m for m in record["media_files"] if m["type"] == "image"]
    audios = [m for m in record["media_files"] if m["type"] == "audio"]
    videos = [m for m in record["media_files"] if m["type"] == "video"]

    selection = {
        "artist_id": record["artist_id"],
        "selected_images": [],
        "skipped_images": [],
        "selected_audio": [],
        "skipped_audio": [],
        "selected_video_frames": [],
        "skipped_videos": [],
        "notes": [],
    }

    images_sorted = sorted(images, key=lambda m: m["path"])
    keep_idx = set(evenly_spaced_indices(len(images_sorted), MAX_IMAGES))
    for i, m in enumerate(images_sorted):
        if i in keep_idx:
            selection["selected_images"].append(m["path"])
        else:
            selection["skipped_images"].append(m["path"])
    if len(images_sorted) > MAX_IMAGES:
        selection["notes"].append(
            f"{len(images_sorted)} images available, sampled {MAX_IMAGES} "
            f"evenly across sorted filenames to avoid upload-order bias."
        )

    audios_sorted = sorted(audios, key=lambda m: m["path"])
    for i, m in enumerate(audios_sorted):
        if i < MAX_AUDIO:
            selection["selected_audio"].append({"path": m["path"], "window_sec": MAX_AUDIO_WINDOW_SEC})
        else:
            selection["skipped_audio"].append(m["path"])
    if len(audios_sorted) > MAX_AUDIO:
        selection["notes"].append(
            f"{len(audios_sorted)} audio files available, analyzed first "
            f"{MAX_AUDIO} (first {MAX_AUDIO_WINDOW_SEC}s each)."
        )

    videos_sorted = sorted(videos, key=lambda m: m["size_bytes"], reverse=True)
    for i, m in enumerate(videos_sorted):
        if i >= MAX_VIDEOS:
            selection["skipped_videos"].append({"path": m["path"], "reason": "exceeds MAX_VIDEOS cap"})
            continue
        full_path = artist_dir / m["path"]
        duration = get_video_duration(full_path)
        if duration is None:
            selection["skipped_videos"].append({"path": m["path"], "reason": "ffprobe failed - unreadable/corrupt"})
            continue
        n_frames = min(MAX_FRAMES_PER_VIDEO, max(1, int(duration // FRAME_INTERVAL_SEC) + 1))
        timestamps = [round(min(t, duration - 0.5), 2) for t in [j * FRAME_INTERVAL_SEC for j in range(n_frames)]]
        selection["selected_video_frames"].append({
            "path": m["path"], "duration_sec": round(duration, 1), "timestamps_sec": timestamps,
        })
    if len(videos_sorted) > MAX_VIDEOS:
        selection["notes"].append(
            f"{len(videos_sorted)} videos available, processed the {MAX_VIDEOS} "
            f"largest by file size; extracted up to {MAX_FRAMES_PER_VIDEO} "
            f"keyframes per video at {FRAME_INTERVAL_SEC}s intervals."
        )

    if not images and not audios and not videos:
        selection["notes"].append("No media of any type available for this artist.")

    return selection


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="outputs/artist_manifest.json")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--out", default="outputs/media_selection.json")
    args = ap.parse_args()

    manifest = json.loads(Path(args.manifest).read_text())
    data_dir = Path(args.data_dir)

    results = [select_for_artist(r, data_dir) for r in manifest]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2))

    print(f"Media selection written for {len(results)} artists -> {out_path}")
    for r in results:
        n_img, n_aud, n_vid = len(r["selected_images"]), len(r["selected_audio"]), len(r["selected_video_frames"])
        print(f"  {r['artist_id']}: {n_img} images, {n_aud} audio, {n_vid} videos selected")


if __name__ == "__main__":
    main()
