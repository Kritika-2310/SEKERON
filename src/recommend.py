"""
recommend.py

For each hirer brief (from brief_parse.py), sends the brief's structured
intent + all candidate artists' capability records (from the matching
category, from capability_extract.py) to Gemini, and asks for a top-2
ranked shortlist with reasons, trade-offs, assumptions, and up to two
prioritized refinement questions.

Category filtering happens in CODE, not left to the LLM - only artists
whose folder-category matches what the brief needs are sent as candidates.

Output: outputs/recommendations.json
"""

import argparse
import json
import os
import time
from pathlib import Path

from google import genai
from dotenv import load_dotenv

load_dotenv()

MODEL_NAME = "gemini-flash-lite-latest"

SYSTEM_PROMPT = """You are matching a hirer's brief to the two best-fit artists from a \
candidate pool, for a creative marketplace. You are given the hirer's structured intent \
(explicit constraints, assumptions, risks, unknowns, priority signal) and evidence-backed \
capability records for each candidate artist (claimed vs demonstrated, with confidence \
levels and citations).

RULES:
- Recommend the two best candidates even if the brief is incomplete - do not wait for a \
perfect match. Use "reasonable_assumptions" already identified in the brief; do not invent \
new unstated requirements.
- For each recommended artist, explain which of THEIR demonstrated (not claimed) signals \
matter for THIS brief, and which signals do not apply or are absent.
- Explicitly state trade-offs and any assumptions you are making to justify the pick.
- Do NOT use reliability, punctuality, professionalism, or popularity as a factor - \
capability and fit only.
- After the shortlist, write "Improve your matches": at most TWO refinement questions, \
each with a one-sentence explanation of how a different answer could materially change \
the ranking. If the brief already has enough information that no question would change \
the ranking, say so explicitly instead of inventing a question.

Return ONLY valid JSON, no markdown fences, matching exactly:
{
  "brief_source_file": "...",
  "category": "...",
  "shortlist": [
    {
      "rank": 1,
      "artist_id": "...",
      "reasons": ["..."],
      "relevant_demonstrated_signals": ["..."],
      "non_applicable_or_absent_signals": ["..."],
      "trade_offs": ["..."],
      "assumptions_made": ["..."]
    }
  ],
  "overall_uncertainty_note": "one or two sentences on how sparse/complete the brief was and how that affected ranking confidence",
  "improve_your_matches": [
    {"question": "...", "why_it_matters": "...", "potential_ranking_impact": "..."}
  ]
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


def category_for_brief(category_needed):
    mapping = {
        "photographer": "photographer",
        "musician": "musician",
        "video_editor": "video_editor",
        "video editor": "video_editor",
    }
    return mapping.get(category_needed.strip().lower(), category_needed)


def recommend_for_brief(client, intent, intelligence):
    category = category_for_brief(intent.get("category_needed", ""))
    candidates = [r for r in intelligence.values() if r.get("category") == category]

    if not candidates:
        return {
            "brief_source_file": intent.get("source_file"),
            "category": category,
            "error": f"no candidates found for category '{category}'",
        }

    prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"HIRER BRIEF (structured intent):\n{json.dumps(intent, indent=2)}\n\n"
        f"CANDIDATE ARTISTS ({len(candidates)} total, category={category}):\n"
        f"{json.dumps(candidates, indent=2)}\n"
    )

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
        parsed = {
            "brief_source_file": intent.get("source_file"),
            "category": category,
            "error": "failed_to_parse_json",
            "raw_response": raw,
        }
    return parsed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--intents", default="outputs/brief_intents.json")
    ap.add_argument("--intelligence", default="outputs/artist_intelligence.jsonl")
    ap.add_argument("--out", default="outputs/recommendations.json")
    args = ap.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY not set. Add it to .env or export it.")
    client = genai.Client(api_key=api_key)

    intents = json.loads(Path(args.intents).read_text())
    intelligence = load_intelligence(Path(args.intelligence))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    results = []
    already_done_files = set()
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text())
            if isinstance(existing, list):
                results = existing
                already_done_files = {r.get("brief_source_file") for r in results}
        except Exception:
            pass
    if already_done_files:
        print(f"Resuming - already done: {already_done_files}")

    for intent in intents:
        src = intent.get("source_file")
        if src in already_done_files:
            continue
        print(f"Recommending for {src}...")

        max_retries = 3
        for attempt in range(max_retries):
            try:
                result = recommend_for_brief(client, intent, intelligence)
                break
            except Exception as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    wait = 60 * (attempt + 1)
                    print(f"  Rate limited. Waiting {wait}s ({attempt+1}/{max_retries})...")
                    time.sleep(wait)
                    if attempt == max_retries - 1:
                        print("  Still rate limited. Saving progress, rerun later to resume.")
                        out_path.write_text(json.dumps(results, indent=2))
                        return
                else:
                    raise

        results.append(result)
        out_path.write_text(json.dumps(results, indent=2))

    print(f"\nDone -> {out_path}")


if __name__ == "__main__":
    main()
