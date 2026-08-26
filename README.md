# README

## Approach

Given a hirer's incomplete conversation, this system recommends the two best-fit artists
from a 15-artist pool, grounded in what their supplied media actually demonstrates —
not what their profile claims. The pipeline runs in five stages, each a standalone,
resumable script:

1. **`ingest.py`** — walks the artist folders, reads each `profile.docx`, lists real
   media files (filtering junk), and logs data-quality anomalies rather than silently
   fixing them (ID collisions, category-label mismatches, missing media).
2. **`media_select.py`** — decides which media to actually analyze. Images: evenly
   spaced sample, capped. Audio: first N seconds of up to 3 files. Video: largest files
   first (proxy for substantive vs. throwaway clips), sparse keyframes at fixed
   intervals rather than every frame. Every skip is logged with a reason.
3. **`capability_extract.py`** — sends only the selected media + profile text to Gemini
   per artist, with a prompt that forces claimed/demonstrated separation, per-file
   evidence citation, and explicit uncertainty when media can't be verified as the
   artist's own work. Output: `artist_intelligence.jsonl`.
4. **`brief_parse.py`** — parses each hirer conversation into structured intent
   (explicit constraints vs. reasonable assumptions vs. contradictions/risks vs.
   unknowns vs. priority signal).
5. **`recommend.py`** / **`rerank.py`** — matches parsed brief intent against the
   category-filtered candidate pool's capability records, producing a top-2 shortlist
   with reasons, trade-offs, assumptions, and up to two prioritized refinement
   questions. `rerank.py` re-derives the ranking from the *updated* requirement rather
   than adjusting scores on the original shortlist, since a follow-up can change what
   "fit" means (e.g. background ambience vs. a headline performance are different
   demonstrated-capability asks).

Category filtering (which artists are even candidates for a brief) happens in code, not
left to the LLM — the LLM's job is ranking and reasoning within the correct pool, not
re-deciding category membership each time.

## Setup

```bash
pip install python-docx google-genai python-dotenv --break-system-packages
sudo apt-get install -y ffmpeg
echo "GEMINI_API_KEY=your_key_here" > .env
```

## Run command (single command, in order)

```bash
python src/ingest.py --data-dir data --out outputs/artist_manifest.json
python src/media_select.py --manifest outputs/artist_manifest.json --data-dir data --out outputs/media_selection.json
python src/capability_extract.py --out outputs/artist_intelligence.jsonl
python src/brief_parse.py --briefs-dir hirer_conversations --out outputs/brief_intents.json
python src/recommend.py --intents outputs/brief_intents.json --intelligence outputs/artist_intelligence.jsonl --out outputs/recommendations.json
python src/rerank.py --original-brief hirer_conversations/01_cafe_music_whatsapp.txt \
    --update follow_up_update/01_cafe_music_update.txt \
    --original-recommendation outputs/recommendations.json \
    --intelligence outputs/artist_intelligence.jsonl \
    --out outputs/updated_recommendation.json
```

`capability_extract.py` and `recommend.py` are resumable: if a run is interrupted by a
rate limit, rerunning the same command skips artists/briefs already written to the
output file rather than re-spending API quota.

## Media selection strategy

Full-portfolio processing (every image, every video second) was out of scope for a
6-hour timebox and wasteful against free-tier API quota. Instead:
- **Images**: capped at 6 per artist, evenly spaced across the sorted file list (not
  "first N") to avoid bias toward upload order.
- **Audio**: capped at 3 files per artist, first 45 seconds each — later files from the
  same artist are usually a repeat of the same vocal/production signal, not new
  information.
- **Video**: capped at 4 videos per artist (largest files first, as a proxy for
  substantive vs. throwaway clips), up to 5 keyframes per video at 8-second intervals
  rather than every frame.

Every skip is logged in `media_selection.json` with a reason, not silently dropped.

## Implemented choices worth noting

- **Model**: Gemini `gemini-flash-lite-latest` (free tier) for all LLM calls — handles
  text, image, and audio natively in one API, so no separate vision/audio pipeline was
  needed. Free-tier daily quota (per model) was hit once during development; switching
  model name mid-project resolved it, and both extraction scripts now retry with
  backoff and resume from partial progress rather than re-billing completed work.
- **Canonical artist ID = folder name**, never the internal docx header — two different
  artist folders' internal headers both claimed the ID "V03," and category labels
  inside profiles sometimes disagreed with the folder's actual category.
- **Media citations are filename-labeled explicitly in the prompt** before each
  image/audio part is sent — without this, the model invented generic placeholder
  filenames (`input_file_0.png`) since raw bytes carry no filename metadata.

## Evaluation and limitations

- **No ground truth to score against** — capability records and recommendations were
  spot-checked against manual review of the source conversations and files (documented
  in the demo), not against a labeled test set. This is a real limitation: correctness
  currently rests on prompt design and manual spot-checks, not automated evaluation.
- **One artist (M03_Raghav_Sen)** has media whose filenames indicate stock/library
  audio rather than personal recordings; the system flags this explicitly as
  unverifiable rather than trusting or discarding it, and produces zero demonstrated
  capabilities as a result — this is intentional, not a pipeline failure.
- **One photographer (PO4_Drift)** has profile text with no matching media context in
  places; handled as a low-evidence case, not a crash.
- **Video-frame sampling (8s intervals, largest-file-first) is a heuristic**, not a
  guarantee of catching every relevant moment in a clip — a genuinely important 2-second
  moment between sampled frames could be missed.
- **Geographic/logistic fit (e.g. "must be in Gurgaon or Delhi") is not verified**
  against any artist location field with confidence, since profile location claims are
  themselves unverified text; the system surfaces this as a flagged unknown rather than
  silently assuming fit.
