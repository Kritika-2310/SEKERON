"""
rerank.py

Applies a follow-up update to one brief's original recommendation and
produces a re-ranked shortlist, explicitly stating what changed and why.

This does NOT just re-score the same candidate pool with adjusted
weights - it re-examines whether the ORIGINAL shortlist's demonstrated
evidence still supports the (possibly changed) requirement, since a
follow-up can change what "fit" even means.

Output: outputs/updated_recommendation.json
"""

import argparse
import json
import os
from pathlib import Path

from google import genai
from dotenv import load_dotenv

load_dotenv()

MODEL_NAME = "gemini-flash-lite-latest"

SYSTEM_PROMPT = """You are re-ranking a hirer's artist shortlist after a follow-up update \
changed or added information to their original brief.

You are given: the original hirer conversation, the original ranked shortlist and reasoning, \
the follow-up update message(s), and the full candidate pool's evidence-backed capability \
records (for the same category).

CRITICAL: A follow-up can change WHAT is being asked for, not just add a detail to the same \
ask (e.g. "background ambience for 3 hours" vs "a 45-minute headline performance" are \
different demonstrated-capability requirements, even though both are still "live music"). \
Before re-scoring, explicitly check whether the ORIGINAL shortlisted artists' demonstrated \
evidence (not their claims) still supports the (possibly changed) requirement. Do not assume \
the original picks are still correct just because they were correct before - re-derive the \
ranking from the candidate pool's evidence and the UPDATED requirement.

RULES:
- Recommend the top two again (may be same artists, reordered, or different artists - \
follow the evidence).
- Explicitly state what changed between the original brief and the update.
- Explicitly state whether the requirement itself changed shape (not just a parameter like \
budget), and why that does or doesn't affect which capabilities matter.
- State what remains unresolved/unknown even after the update.
- Do NOT use reliability, punctuality, professionalism, or popularity as a factor.

Return ONLY valid JSON, no markdown fences, matching exactly:
{
  "brief_source_file": "...",
  "update_source_file": "...",
  "category": "...",
  "what_changed": ["..."],
  "requirement_shape_changed": true,
  "requirement_shape_change_explanation": "...",
  "updated_shortlist": [
    {
      "rank": 1,
      "artist_id": "...",
      "reasons": ["..."],
      "relevant_demonstrated_signals": ["..."],
      "trade_offs": ["..."],
      "assumptions_made": ["..."],
      "changed_from_original": "unchanged | reordered | newly_added | dropped_from_original"
    }
  ],
  "still_unresolved": ["..."],
  "summary_of_what_changed_and_why": "two to three sentences suitable for the required output file"
}
"""


def load_intelligence(path):
    by_id = {}
    for line in path.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            if "artist_id" in r:
                by_id[r["artist_id"]] = r
    return by_id


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--original-brief", default="hirer_conversations/01_cafe_music_whatsapp.txt")
    ap.add_argument("--update", default="follow_up_update/01_cafe_music_update.txt")
    ap.add_argument("--original-recommendation", default="outputs/recommendations.json")
    ap.add_argument("--intelligence", default="outputs/artist_intelligence.jsonl")
    ap.add_argument("--out", default="outputs/updated_recommendation.json")
    args = ap.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY not set. Add it to .env or export it.")
    client = genai.Client(api_key=api_key)

    original_brief_text = Path(args.original_brief).read_text()
    update_text = Path(args.update).read_text()
    all_recs = json.loads(Path(args.original_recommendation).read_text())
    original_rec = next(
        (r for r in all_recs if r.get("brief_source_file") == Path(args.original_brief).name),
        None,
    )
    if original_rec is None:
        raise SystemExit(
            f"Could not find original recommendation for {Path(args.original_brief).name} "
            f"in {args.original_recommendation}"
        )

    intelligence = load_intelligence(Path(args.intelligence))
    category = original_rec.get("category")
    candidates = [r for r in intelligence.values() if r.get("category") == category]

    prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"ORIGINAL HIRER CONVERSATION:\n{original_brief_text}\n\n"
        f"ORIGINAL RANKED RECOMMENDATION:\n{json.dumps(original_rec, indent=2)}\n\n"
        f"FOLLOW-UP UPDATE:\n{update_text}\n\n"
        f"FULL CANDIDATE POOL ({len(candidates)} total, category={category}):\n"
        f"{json.dumps(candidates, indent=2)}\n"
    )

    print("Re-ranking with follow-up update...")
    resp = client.models.generate_content(model=MODEL_NAME, contents=prompt)
    raw = resp.text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"error": "failed_to_parse_json", "raw_response": raw}

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(parsed, indent=2))
    print(f"Done -> {out_path}")


if __name__ == "__main__":
    main()
