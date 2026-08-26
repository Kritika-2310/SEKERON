import argparse
import json
import re
from pathlib import Path

try:
    import docx
except ImportError:
    raise SystemExit("Missing dependency. Run: pip install python-docx")

JUNK_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}
MEDIA_EXTS = {
    "image": {".jpg", ".jpeg", ".png", ".webp", ".heic"},
    "video": {".mp4", ".mov", ".m4v", ".avi"},
    "audio": {".mp3", ".wav", ".m4a", ".aac"},
}

CATEGORY_FOLDER_MAP = {
    "photographers": "photographer",
    "musicians": "musician",
    "video_editors": "video_editor",
}


def media_type_of(path: Path):
    ext = path.suffix.lower()
    for mtype, exts in MEDIA_EXTS.items():
        if ext in exts:
            return mtype
    return None


def read_profile_docx(path: Path) -> dict:
    """Extract raw paragraph text plus a best-effort structured parse.
    Structured fields are best-effort only - capability_extract.py should
    not trust these blindly, since we've seen text/media disagree
    (e.g. a profile claims 'Portfolio: Not provided' while media
    files exist)."""
    d = docx.Document(str(path))
    lines = []
    for p in d.paragraphs:
        # some paragraphs contain embedded newlines (multiple logical
        # lines inside one docx paragraph run) - split them out, or
        # fields like Category/Location/Work preference get swallowed
        # into one value and falsely trigger category_mismatch flags.
        for sub in p.text.split("\n"):
            sub = sub.strip()
            if sub:
                lines.append(sub)
    raw_text = "\n".join(lines)

    structured = {
        "internal_header": lines[0] if lines else None,
        "category_claimed": None,
        "location_claimed": None,
        "work_preference_claimed": None,
        "bio": None,
        "claimed_portfolio_files": [],
    }

    bio_started = False
    portfolio_started = False
    bio_lines = []
    for line in lines:
        low = line.lower()
        if low.startswith("category:"):
            structured["category_claimed"] = line.split(":", 1)[1].strip()
            bio_started = portfolio_started = False
            continue
        if low.startswith("location:"):
            structured["location_claimed"] = line.split(":", 1)[1].strip()
            continue
        if low.startswith("work preference:"):
            structured["work_preference_claimed"] = line.split(":", 1)[1].strip()
            continue
        if low.startswith("bio"):
            bio_started, portfolio_started = True, False
            continue
        if low.startswith("portfolio"):
            portfolio_started, bio_started = True, False
            continue
        if bio_started:
            bio_lines.append(line)
        if portfolio_started:
            if re.search(r"\.\w{2,4}$", line) or "not provided" in low:
                structured["claimed_portfolio_files"].append(line)

    structured["bio"] = " ".join(bio_lines).strip() or None
    return {"raw_text": raw_text, **structured}


def ingest_artist(folder: Path, category_from_dir: str) -> dict:
    flags = []

    docx_files = list(folder.glob("*.docx")) + list(folder.glob("*/*.docx"))
    if not docx_files:
        flags.append("no_profile_docx")
        profile = {}
    else:
        if len(docx_files) > 1:
            flags.append("multiple_profile_docx")
        profile = read_profile_docx(docx_files[0])

    if profile.get("category_claimed") and \
            profile["category_claimed"].strip().lower() != category_from_dir.replace("_", " "):
        flags.append(
            f"category_mismatch: claimed='{profile.get('category_claimed')}' "
            f"vs folder_category='{category_from_dir}'"
        )

    media_files = []
    junk_skipped = 0
    for p in folder.rglob("*"):
        if p.is_dir():
            continue
        if p.name in JUNK_NAMES or p.name.startswith("."):
            junk_skipped += 1
            continue
        if p.suffix.lower() == ".docx":
            continue
        mtype = media_type_of(p)
        if mtype is None:
            flags.append(f"unrecognized_file: {p.name}")
            continue
        media_files.append({
            "path": str(p.relative_to(folder)),
            "type": mtype,
            "size_bytes": p.stat().st_size,
        })

    if not media_files:
        flags.append("no_media")

    return {
        "artist_id": folder.name,
        "category": category_from_dir,
        "internal_header": profile.get("internal_header"),
        "category_claimed": profile.get("category_claimed"),
        "location_claimed": profile.get("location_claimed"),
        "work_preference_claimed": profile.get("work_preference_claimed"),
        "bio": profile.get("bio"),
        "claimed_portfolio_files": profile.get("claimed_portfolio_files", []),
        "media_files": media_files,
        "media_count": len(media_files),
        "junk_files_skipped": junk_skipped,
        "flags": flags,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--out", default="outputs/artist_manifest.json")
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    manifest = []
    seen_ids = {}

    for dir_name, category in CATEGORY_FOLDER_MAP.items():
        cat_dir = data_dir / dir_name
        if not cat_dir.exists():
            print(f"[warn] missing category dir: {cat_dir}")
            continue
        for artist_folder in sorted(p for p in cat_dir.iterdir() if p.is_dir()):
            record = ingest_artist(artist_folder, category)
            manifest.append(record)

            # cross-artist collision check: compare only the leading ID
            # token (e.g. "V03"), not the full header string, since two
            # different artists can share an ID token while the rest of
            # the header (name) differs.
            header = record["internal_header"] or ""
            id_match = re.match(r"\s*([A-Za-z]+\d+)\s*/", header)
            key = id_match.group(1).upper() if id_match else None
            if key:
                if key in seen_ids:
                    record["flags"].append(f"internal_id_collision_with:{seen_ids[key]}")
                    for r in manifest:
                        if r["artist_id"] == seen_ids[key]:
                            r["flags"].append(f"internal_id_collision_with:{record['artist_id']}")
                else:
                    seen_ids[key] = record["artist_id"]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=2))

    print(f"Ingested {len(manifest)} artists -> {out_path}")
    flagged = [m for m in manifest if m["flags"]]
    print(f"{len(flagged)} artists have flags:")
    for m in flagged:
        print(f"  - {m['artist_id']}: {m['flags']}")


if __name__ == "__main__":
    main()
