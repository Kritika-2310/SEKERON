# AI_USAGE.md

## AI tools used

1. **Claude (Anthropic)** — used throughout for planning the system architecture,
   writing/debugging all pipeline code (`ingest.py`, `media_select.py`,
   `capability_extract.py`, `brief_parse.py`, `recommend.py`, `rerank.py`), and drafting
   `decision_note.md` and this README.
2. **Gemini (`gemini-flash-lite-latest`, free tier)** — used at runtime, inside the
   pipeline itself, as the vision/audio/text reasoning engine for capability extraction,
   brief parsing, recommendation, and re-ranking. This is a production dependency of the
   system, not a development aid.

## What Claude produced

- Full first-draft code for all six pipeline scripts, based on the assessment brief and
  on the actual folder/file structure of the supplied dataset (inspected directly, not
  assumed).
- Draft `decision_note.md` and `README.md`, written from the project's actual scope
  decisions and the real data-quality issues found during development (not generic
  boilerplate).
- Debugging support during development: diagnosed and fixed a docx paragraph-splitting
  bug in `ingest.py`, a broken artist-ID-collision check (comparing full header strings
  instead of just the ID token), missing filename labels in Gemini prompts (which caused
  the model to invent placeholder filenames instead of citing real ones), and handled a
  deprecated Gemini SDK / retired model name / free-tier daily rate limit by adding
  retry-with-backoff and resume-from-partial-progress logic.

## What I personally verified or changed

- **Ran every script myself** against the real downloaded dataset in Codespaces —
  nothing in the outputs was accepted without seeing actual command output first.
- **Manually inspected the raw data** before trusting any script output: unzipped and
  read all 15 profile docs and file listings directly, which is how the following were
  caught independently of the pipeline (and later confirmed by the pipeline's own
  logging): the duplicate "V03" internal ID across two different artist folders, the
  category-label mismatches in 4 profiles, the missing/thin media case, and the
  stock-audio filenames for M03_Raghav_Sen.
- **Verified the capability_extract.py output** for the stock-audio case specifically —
  confirmed the model correctly flagged the audio as unverifiable rather than
  fabricating demonstrated skills from it, before accepting the script as working.
- **Verified the re-ranking output** for the café brief follow-up — confirmed the model
  re-derived the ranking from the changed requirement (background ambience → headline
  performance) rather than just re-scoring the same two artists, which was the specific
  failure mode I was checking for given the brief's explicit warning against "silently
  resolving" changed requirements.
- **Chose the model** (`gemini-flash-lite-latest`) myself after hitting a daily quota
  limit on the model Claude initially suggested — tested it manually before rolling it
  out to the full pipeline.
- **All prompts, schemas, and category-specific capability dimensions** in the scripts
  were reviewed and are being submitted as my own design decisions, not blindly copied.