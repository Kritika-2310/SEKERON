# Decision Note

## Decision this system supports
Given a hirer's incomplete conversation, recommend the two most relevant artists from a
15-artist pool (photographers, musicians, video editors), grounded in what their supplied
media actually demonstrates rather than what their profile claims — and re-rank cleanly
when new brief information arrives.

## First-version scope
- Ingest all 15 artist folders + 4 hirer briefs + 1 follow-up update.
- Produce one evidence-backed capability record per artist (claimed vs. demonstrated, kept
  separate).
- Produce an initial top-2 shortlist per brief with reasons, trade-offs, assumptions, and up
  to two prioritized refinement questions.
- Re-rank brief 081 (café) using the follow-up update and explain what changed.

## Non-goals
- No frontend, no deployment, no model training, no web scraping.
- No inference of reliability, punctuality, professionalism, or character from media —
  scored dimensions are capability-only.
- No attempt to "fix" or reconcile inconsistent source data (see Assumptions/Risks) —
  inconsistencies are logged and surfaced, not silently resolved.

## Capability dimensions per category
- **Photographer**: subject/context specialization (event, product, portrait), lighting
  control, editing/retouching style, solo vs. team execution, self-sufficiency (can they
  run a shoot without a studio/crew).
- **Musician**: genre and instrumentation, live vs. studio-only evidence, vocal/production
  quality, performance format fit (background ambience vs. headline set), volume/stage
  footprint implied by the evidence.
- **Video editor**: pacing/style (narrative vs. commercial vs. social/short-form), source
  material handling (raw multi-clip footage vs. single-shot), captioning/sound-design
  evidence, output format range (vertical/square/etc.) if demonstrated.

## Assumptions and risks
- **Folder name is the canonical artist ID.** Internal docx headers are unreliable — IDs
  collide across artists (e.g. two folders both self-labeled "V03"), and one profile's
  stated category conflicts with its own folder placement. Text is data, not ground truth.
- **Claimed portfolio filenames in profile text may not match actual media filenames**
  (seen in two video-editor profiles) — likely an anonymization artifact, not fraud, but
  treated as unverifiable rather than assumed either way.
- **One artist's media consists of filenames matching royalty-free stock-audio libraries**,
  not personal recordings — likely the assessment's intentional "damaged/incomplete" case.
  Treated as *unverifiable* evidence (not silently trusted, not silently discarded) and
  flagged explicitly in that artist's record.
- **Large raw video files** mean full-frame/full-duration processing isn't feasible in
  scope — a capped keyframe/clip-sampling strategy is used, with selections and skips
  logged per artist.
- **Sparse hirer briefs mean some assumptions are unavoidable** (e.g. inferring "candid
  coverage" priority from one explicit trade-off statement) — assumptions are labeled as
  such in outputs, distinct from explicit constraints.
- **Confidence scoring** is evidence-count and evidence-relevance based (more directly
  on-topic media = higher confidence), not a subjective quality judgment — stated
  explicitly per artist record so it's auditable, not a black box.
