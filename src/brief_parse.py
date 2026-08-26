"""
brief_parse.py

Reads each hirer conversation .txt file and uses an LLM to extract
structured intent: explicit constraints, reasonable assumptions,
contradictions/risks, unknowns, and a priority signal.

Requires GEMINI_API_KEY in a .env file or environment variable.

Run:
    python src/brief_parse.py --briefs-dir hirer_conversations --out outputs/brief_intents.json
"""

import argparse
import json
import os
from pathlib import Path

from google import genai
from dotenv import load_dotenv

load_dotenv()

MODEL_NAME = "gemini-flash-lite-latest"

SYSTEM_PROMPT = """You are analyzing a hirer's conversation with a creative marketplace, \
looking for a photographer, musician, or video editor. Extract structured intent.

Return ONLY valid JSON, no markdown fences, no preamble, matching this exact schema:

{
  "category_needed": "photographer" | "musician" | "video_editor",
  "explicit_constraints": ["..."],
  "reasonable_assumptions": ["..."],
  "contradictions_or_risks": ["..."],
  "important_unknowns": ["..."],
  "priority_signal": "..."
}

Rules:
- explicit_constraints must be things actually stated, not inferred - if you're inferring, it belongs in reasonable_assumptions instead.
- Do not invent a budget, date, or format if none was given - put "not specified" in important_unknowns instead.
- Keep each list item to one sentence.
"""


def parse_one_brief(client, text, filename):
    prompt = f"{SYSTEM_PROMPT}\n\nConversation file: {filename}\n\n---\n{text}\n---"
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
    parsed["source_file"] = filename
    return parsed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--briefs-dir", default="hirer_conversations")
    ap.add_argument("--out", default="outputs/brief_intents.json")
    args = ap.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY not set. Add it to .env or export it.")
    client = genai.Client(api_key=api_key)

    briefs_dir = Path(args.briefs_dir)
    brief_files = sorted(
        f for f in briefs_dir.glob("*.txt")
        if "update" not in f.stem.lower()
    )

    results = []
    for f in brief_files:
        print(f"Parsing {f.name}...")
        text = f.read_text()
        result = parse_one_brief(client, text, f.name)
        results.append(result)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\nParsed {len(results)} briefs -> {out_path}")


if __name__ == "__main__":
    main()
