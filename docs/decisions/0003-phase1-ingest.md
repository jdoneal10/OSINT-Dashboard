# ADR 0003 — Phase 1 ingest: ACLED and CBP

- **Status:** Accepted
- **Date:** 2026-11-11
- **Scope:** `backend/app/ingest/{acled,cbp,http,raw,runs}.py`, `backend/app/enrich/actors.py`, migration `0002`, `data/reference/sources.yaml`, `data/reference/border_adjacency.yaml`

## Context

Phase 1 brings in the first live data. Two sources are involved:
- **ACLED:** violence events for IR1 (violence and activity), IR2 (territorial contestation) and IR3 (border correlation).
- **CBP:** encounters and drug seizures by area of responsibility, for IR3.

Both sources impose terms that shape the design. The terms were read on 2026-11-11 and are recorded in `docs/data-sources.md`.

## Decisions

### ACLED licence and handling
- **Licence:** the owner confirmed the use is **personal, non-commercial** (EULA effective 2026-11-01, s.1.2). Internal analysis only; the database and raw pages are not shared.
- **Access:** through the API only (s.3.3, s.7.2), with OAuth credentials kept in macOS Keychain.
- **No ACLED content goes into any LLM** — prompts, embeddings or knowledge bases (s.7.1) — unless ACLED gives written consent. **This binds Phase 2 and Phase 4.** The Claude pipeline must exclude ACLED records and text, and so must INTSUM drafting. *Superseded by ADR 0006: ACLED gave written consent on 2026-11-11 for processing with Claude.*
- **Attribution:** every visual that shows ACLED data carries it on the visual itself, per the Attribution Policy:
  - "ACLED (Armed Conflict Location & Event Data)" with a link
  - the access date
  - the filters applied
- **Portfolio material:** external material must be transformative and must not let anyone reverse-engineer the data (s.3.1). Portfolio screenshots and the public demo (Phase 5) therefore use synthetic or aggregated data. *Amended by ADR 0006: professional, non-profit display with ACLED attribution is allowed.*
- **Records:** `ingest_runs` and the raw snapshots serve s.15's three-year record-keeping requirement.

### ACLED scope: the six Mexican border states only
- **Query:** `country=Mexico`, kept only when the event's admin1 name matches one of the six states (accent- and case-insensitive, accepting long forms such as "Coahuila de Zaragoza") or its point falls inside one of the six reference polygons.
- **Why not the U.S. side:** U.S.-side ACLED events in the AOI are mostly protests involving U.S. police. They don't serve IR3, and they press against hard rule 4. The U.S. side is covered by CBP statistics.
- **Revisions:** an event revised so that it falls outside the AOI is removed.

### ACLED revisions and deletions
- **Upsert key:** `event_id_cnty`, which ACLED keeps stable across edits.
- **Incremental pulls:** use the `timestamp` watermark of the last successful run.
- **Deletions:** a weekly pull of `/api/deleted/read` **hard-deletes** matching events, cascading to actor links. The deleted IDs stay in the raw snapshot for audit. The deletion watermark starts at the first backfill, since events deleted before then never reached us.

### Fixtures
**ACLED test fixtures are fully synthetic:** real field schema, fabricated values. No ACLED data enters git (hard rule 5). CBP fixtures are also synthetic, but use CBP's real headers and page markup.

### Actor normalization v1 and roles
- **Method:** rule-based — alias matching, `Parent: Detail` handling, faction child actors. Unmatched groups become new actors typed from ACLED's inter category, and ACLED is cited.
- **Roles mirror ACLED's dyad exactly:** `actor1`, `actor2`, `assoc_actor1`, `assoc_actor2`. ACLED's actor1 is not necessarily a perpetrator, so we make no perpetrator or target claim. Those roles are reserved for Phase 2 extraction.
- **Organizations and groups only.** Never persons (hard rule 3).

### Admiralty defaults and confidence
- **Initial source reliability:** ACLED **B** (curated, documented methodology, but a living dataset). CBP **A** (official administrative statistics for its own actions). Other reference sources are A.
- **Baseline record confidence** comes from the grade: A 0.90, B 0.75, C 0.60, D 0.40, E 0.20, F unset. Corroboration scoring arrives in Phase 2.

### CBP: robots.txt, snapshots, manual FY20 import
- **robots.txt:** cbp.gov disallows `/sites/default/files/assets/documents/`, the only place the FY20–FY23 files live. The ingester never fetches there. The guard is in code, on top of the robots check, and a test covers it.
- **Manual FY20 import:** the owner downloads those files in a browser and imports them with `make ingest SOURCE=cbp FILE=…`. Their posted date is looked up on CBP's page, so an older file never outranks a newer revision.
- **Snapshots:** each file is a new `snapshot_date`, so revisions never overwrite. The API serves the latest snapshot per AOR, month and dimension, and `as_of` shows history. Unchanged files are skipped by sha256.
- **Notices:** every CBP view carries "Uses CBP data; not endorsed by CBP", the retrieval date, and the caveat that counts reflect enforcement activity, not flow.

### Sector ↔ state adjacency
`border_adjacency.yaml` maps each USBP sector to the Mexican states it borders and pairs it with an OFO field office. It is **analyst-derived**, because no public sector boundary data exists (ADR 0002), and it is labeled as such wherever it is used.

## Consequences
- Phase 2's LLM pipeline needs an explicit source filter so that ACLED content can never reach Claude. That needs its own ADR if ACLED ever grants consent.
- Expanding ACLED to all of Mexico in Phase 2 only means widening the AOI filter. The raw pages already cover the whole country.
- A missing FY20 import leaves the border panel starting at FY21. The panel reports what it has.
