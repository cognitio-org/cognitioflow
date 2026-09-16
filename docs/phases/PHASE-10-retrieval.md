# Phase 10 — Retrieval that puts the course materials first, and recall that adapts

Branch: `phase-10-retrieval`. Depends on Phase 1 (`db()`), Phase 2 (`storage.py`), Phase 5 (Cloud Run image).

## The rule this phase exists to serve
**The user's own course materials are supreme.** Retrieval may change *which parts* of the ticked files reach the model and
in what order — never *whether* the answer comes from them. Model memory is still only allowed as `[OUTSIDE FILES]`, and the
authority hierarchy (annotated WG notes > lecture > slides > reader/Schütze) decides ties. Nothing is dropped silently.

## Decisions — settled (2026-09-16)
- **Embeddings run inside the app's own container**: `fastembed` (ONNX runtime, ~21 MB) with **BAAI/bge-small-en-v1.5**
  (384 dimensions, ~33 MB). No API key, no new provider, no per-call cost, nothing leaves Google Cloud. Model id in
  `EMBED_MODEL`; the environment selects the backend, as with the other seams.
- **Vectors live in Neon** with `pgvector` (migration `007_chunks.sql`). Today's corpus (~3M characters of course text)
  is ~3–4k chunks ≈ 5 MB, far inside the Free plan's 512 MB branch limit.
- **Chunking:** ~1,000 characters with ~150 overlap, split on headings and paragraphs so a chunk is a readable passage.
  Each chunk keeps `file_id`/`note_id`, `week`, `kind`, heading path and character offsets, so every quote can be traced back.
- **Course-first ranking:** similarity, then an authority weight by `kind` (WG notes > lecture/transcript > slides > reader),
  then recency of the user's own edits. The tutor's file selection ("ticked files") stays the filter — retrieval never widens it.
- **Nothing disappears:** the chunk budget always includes at least one chunk from every ticked file, and the reply's
  Reading strip names any file that was trimmed. A per-message **Read everything** toggle restores today's whole-file behaviour.
- **Whole-file tasks keep whole files:** reconcile, draft notes, clean garble and case-map cards are unchanged — they must see
  every line. Retrieval applies to the tutor chat (drill / explain) and to ⌘K.
- **⌘K becomes hybrid:** substring matches first (exact case names and article numbers must never be missed), then semantic
  neighbours, clearly separated.
- **Recall moves to FSRS** (`py-fsrs`, MIT): each card's interval comes from the user's own review history. `SCHEDULER=sm2`
  keeps the old behaviour; existing `reviews` rows seed the new scheduler so no history is lost.
- **Indexing is a job, not a thread**: reuse the `jobs` table (kind `embed`), one file per poll, so a long import can't block a
  request and a restart resumes it (CLAUDE.md: no state in process memory).

## Parts
- **A. `embed.py` seam** — `embed(texts) -> vectors`, `dimensions()`, `ready()`. Backends: `local` (fastembed, default) and
  `none` (tests, no model download). `run.py` never imports fastembed.
- **B. Chunk + index** — on upload, on note save (debounced) and on demand; `jobs` row per file; `chunks` table with the
  vector column and an IVFFlat index.
- **C. Retrieval** — `search(course, query, ticked_only=True, budget_chars=...)`: vector search + authority weighting +
  per-file guarantee; returns passages with provenance for the prompt's Reading block.
- **D. Tutor** — the files block becomes the retrieved passages (cache order preserved: rules → passages → mode). The
  Reading strip lists files used and files trimmed. **Read everything** restores whole files.
- **E. ⌘K** — hybrid results, meaning-based matches marked as such.
- **F. FSRS** — scheduling from review history, with the SM-2 switch and a one-off backfill.

## Acceptance
- [ ] A drill turn on European Law sends ≤ ~12k tokens instead of ~45k, and the answer still cites the same WG notes.
- [ ] Every ticked file appears at least once in the Reading strip, or is named as trimmed.
- [ ] A question whose wording never appears in the files (e.g. "can packaging rules block imports?") retrieves the Dassonville passage.
- [ ] Reconcile, draft notes and clean garble still read whole files, byte for byte as today.
- [ ] Turning off retrieval (`RETRIEVAL=off`) reproduces today's behaviour exactly.
- [ ] Re-indexing 31 files completes as jobs, survives a restart, and costs nothing beyond CPU.
- [ ] FSRS reproduces every existing card's next due date at least as well as SM-2 on the user's own history; `SCHEDULER=sm2` switches back.
- [ ] `docker build` grows by < 100 MB; cold start stays under 5 s.
