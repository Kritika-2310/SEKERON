"""
capability_extract.py

For each artist, sends ONLY the media selected by media_select.py
to Gemini along with the profile bio/claims, and asks for one
evidence-backed capability record per artist.

RESUMABLE: if outputs/artist_intelligence.jsonl already has records,
already-processed artists are skipped, not re-billed against quota.

Output: outputs/artist_intelligence.jsonl (one JSON record per line)
Requires GEMINI_API_KEY in .env.
"""

import argparse
import json
import mimetypes
import os
import subprocess
import tempfile
import time
from pathlib import Path

from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

MODEL_NAME = "gemini-flash-lite-latest"

CATEGORY_DIMENSIONS = {
    "photographer": (
        "subject/context specialization (event, product, portrait), "
        "lighting control, editing/retouching style, solo vs team execution, "
        "self-sufficiency (can run a shoot without a studio/crew)"
    ),
    "musician": (
        "genre and instrumentation, live vs studio-only evidence, "
        "vocal/production quality, performance format fit (background "
        "ambience vs headline set), volume/stage footprint implied by evidence"
    ),
    "video_editor": (
        "pacing/style (narrative vs commercial vs social/short-form), "
        "source material handling (raw multi-clip footage vs single-shot), "
        "captioning/sound-design evidence, output format range if demonstrated"
    ),
}

SYSTEM_PROMPT_TEMPLATE = """You are building an evidence-backed capability record for a \
{category}, for a creative-marketplace matching system. You will be shown the artist's \
profile bio, their claimed portfolio description, and a SAMPLE of their actual media \
(images / audio clips / video keyframes - NOT their complete portfolio).

Category-specific dimensions to consider for a {category}: {dimensions}.

CRITICAL RULES:
- Distinguish CLAIMED (what the bio/profile text says) from DEMONSTRATED (what the actual \
media shows). Do not let claims inflate the demonstrated assessment.
- Every demonstrated capability must cite which specific file (and timestamp, if a video \
frame) it comes from. No evidence, no claim.
- Do NOT infer reliability, punctuality, professionalism, popularity, or personal character \
from the media or bio. Capability only.
- If media is missing, ambiguous, or its authenticity/attribution to this artist is \
uncertain (e.g. filenames suggest stock/library content rather than the artist's own work), \
say so explicitly in "unknowns" - do not silently trust or silently discard it.
- confidence must be "high", "medium", or "low" and briefly justified by evidence volume/\
relevance, not a vibe.

Return ONLY valid JSON, no markdown fences, matching exactly:
{{
  "artist_id": "{artist_id}",
  "category": "{category}",
  "claimed": ["..."],
  "demonstrated": [
    {{"skill": "...", "evidence": ["filename or filename@timestamp"], "confidence": "high|medium|low", "confidence_reason": "..."}}
  ],
  "unknowns": ["..."],
  "overall_notes": "one or two sentences, evidence-grounded summary"
}}
"""


def extract_frames(video_path, timestamps, tmp_dir, prefix):
    frame_paths = []
    for t in timestamps:
        out_file = tmp_dir / f"{prefix}_{t}.jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-ss", str(t), "-i", str(video_path),
             "-frames:v", "1", "-q:v", "3", str(out_file)],
            capture_output=True, timeout=30,
        )
        if out_file.exists():
            frame_paths.append((out_file, t))
    return frame_paths


def trim_audio(audio_path, window_sec, tmp_dir, prefix):
    out_file = tmp_dir / f"{prefix}_trimmed.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(audio_path), "-t", str(window_sec),
         "-acodec", "libmp3lame", str(out_file)],
        capture_output=True, timeout=60,
    )
    return out_file if out_file.exists() else None


def build_parts(genai_types, artist_dir, selection, tmp_dir):
    parts = []
    included = []

    for img_rel in selection["selected_images"]:
        p = artist_dir / img_rel
        mime, _ = mimetypes.guess_type(str(p))
        if mime and p.exists():
            parts.append(f"The following image's filename is exactly: {img_rel}")
            parts.append(genai_types.Part.from_bytes(data=p.read_bytes(), mime_type=mime))
            included.append(img_rel)

    for aud in selection["selected_audio"]:
        p = artist_dir / aud["path"]
        if not p.exists():
            continue
        trimmed = trim_audio(p, aud["window_sec"], tmp_dir, Path(aud["path"]).stem)
        if trimmed:
            label = f"{aud['path']} (first {aud['window_sec']}s)"
            parts.append(f"The following audio clip's filename is exactly: {aud['path']} (this excerpt is the first {aud['window_sec']}s)")
            parts.append(genai_types.Part.from_bytes(data=trimmed.read_bytes(), mime_type="audio/mpeg"))
            included.append(label)

    for vid in selection["selected_video_frames"]:
        p = artist_dir / vid["path"]
        if not p.exists():
            continue
        frames = extract_frames(p, vid["timestamps_sec"], tmp_dir, Path(vid["path"]).stem)
        for frame_path, t in frames:
            label = f"{vid['path']}@{t}s"
            parts.append(f"The following image is a keyframe extracted from video filename: {vid['path']}, at exactly {t} seconds. When citing, use exactly this format: \"{label}\"")
            parts.append(genai_types.Part.from_bytes(data=frame_path.read_bytes(), mime_type="image/jpeg"))
            included.append(label)

    return parts, included


def extract_one_artist(client, record, selection, data_dir, tmp_dir):
    category = record["category"]
    artist_dir = data_dir / (
        "photographers" if category == "photographer" else
        "musicians" if category == "musician" else
        "video_editors"
    ) / record["artist_id"]

    parts, included_evidence = build_parts(types, artist_dir, selection, tmp_dir)

    if not parts:
        return {
            "artist_id": record["artist_id"],
            "category": category,
            "claimed": [record.get("bio")] if record.get("bio") else [],
            "demonstrated": [],
            "unknowns": ["No usable media available for this artist - assessment based on profile text only, which is unverifiable."],
            "overall_notes": "No media evidence; capability cannot be demonstrated, only claimed.",
            "evidence_files_reviewed": [],
        }

    sys_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        category=category,
        dimensions=CATEGORY_DIMENSIONS[category],
        artist_id=record["artist_id"],
    )
    context_text = (
        f"Profile bio: {record.get('bio') or 'none provided'}\n"
        f"Claimed portfolio files (unverified against actual media): "
        f"{record.get('claimed_portfolio_files') or 'none listed'}\n"
        f"Known data-quality flags for this artist: {record.get('flags') or 'none'}\n"
    )

    contents = [sys_prompt, context_text] + parts
    resp = client.models.generate_content(model=MODEL_NAME, contents=contents)
    raw = resp.text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {
            "artist_id": record["artist_id"], "category": category,
            "error": "failed_to_parse_json", "raw_response": raw,
        }

    parsed["evidence_files_reviewed"] = included_evidence
    return parsed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="outputs/artist_manifest.json")
    ap.add_argument("--selection", default="outputs/media_selection.json")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--out", default="outputs/artist_intelligence.jsonl")
    ap.add_argument("--artist", default=None, help="process only this artist_id (debugging)")
    args = ap.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY not set. Add it to .env or export it.")
    client = genai.Client(api_key=api_key)

    manifest = {r["artist_id"]: r for r in json.loads(Path(args.manifest).read_text())}
    selections = {s["artist_id"]: s for s in json.loads(Path(args.selection).read_text())}
    data_dir = Path(args.data_dir)

    artist_ids = [args.artist] if args.artist else list(manifest.keys())

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    already_done = set()
    if out_path.exists() and not args.artist:
        for line in out_path.read_text().splitlines():
            if line.strip():
                try:
                    already_done.add(json.loads(line)["artist_id"])
                except Exception:
                    pass
        if already_done:
            print(f"Resuming - {len(already_done)} artists already done, skipping: {sorted(already_done)}")

    artist_ids = [a for a in artist_ids if a not in already_done]
    write_mode = "a" if already_done else "w"

    with tempfile.TemporaryDirectory() as tmp, open(out_path, write_mode) as out_f:
        tmp_dir = Path(tmp)
        for artist_id in artist_ids:
            print(f"Extracting capabilities: {artist_id}...")
            record = manifest[artist_id]
            selection = selections.get(artist_id, {
                "selected_images": [], "selected_audio": [], "selected_video_frames": []
            })

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    result = extract_one_artist(client, record, selection, data_dir, tmp_dir)
                    break
                except Exception as e:
                    if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                        wait = 60 * (attempt + 1)
                        print(f"  Rate limited. Waiting {wait}s before retry ({attempt+1}/{max_retries})...")
                        time.sleep(wait)
                        if attempt == max_retries - 1:
                            print(f"  Still rate limited after {max_retries} retries. "
                                  f"Stopping here - rerun the same command later to resume "
                                  f"from {artist_id} onward.")
                            return
                    else:
                        raise

            out_f.write(json.dumps(result) + "\n")
            out_f.flush()

    print(f"\nDone -> {out_path}")


if __name__ == "__main__":
    main()
