# ADR 0004 — Phase 2: unstructured sources and the hybrid AI pipeline

- **Status:** Accepted
- **Date:** 2026-11-11
- **Scope:** `data/reference/feeds.yaml`, `backend/app/ingest/{gdelt,rss,designations,sesnsp}.py`, `backend/app/enrich/{llm,local_filter,extract,geocode,dedupe,admiralty,analyze}.py`, the Phase 2 AOI

## Context

Phase 2 adds news, press releases and designations, run through a hybrid pipeline: a local relevance filter, then Haiku for translation and extraction, then Sonnet for analysis. It also expands the AOI to all of Mexico.

Source terms and robots.txt files were checked on 2026-11-11. Model facts come from the Claude API reference as of 2026-11-03.

## Decisions

### 1. News text policy (owner decision)
- **Full text** is fetched, stored locally and processed from any outlet whose robots.txt permits our generic client. This is private, non-commercial research.
- **Accepted risk:** this includes outlets whose terms prohibit reproduction, specifically **Proceso** (total or partial reproduction prohibited by any means) and **Milenio** (copying prohibited without written permission, even non-commercially). The owner accepted that risk on 2026-11-11. Each entry in `feeds.yaml` records its outlet's terms.
- **Excluded:**
  - Outlets whose robots.txt blocks **AI agents** (ClaudeBot, anthropic-ai): Border Report, El Siglo de Torreón (which also signals `ai-train=no`), and congress.gov/CRS. Processing their text with Claude is exactly what that signal declines.
  - Outlets whose robots.txt disallows our generic client: El Universal, El Diario de Juárez.
  - Agencies whose robots.txt returns 403: DEA, USCG.
- **robots.txt is re-checked at fetch time** by the existing polite client. A later change upstream stops ingestion automatically.
- **Nothing is redistributed:** article text never leaves this machine except as API input to Claude, which CLAUDE.md permits for public article text.
- **Revisit:** if the project ever goes public (Phase 5), the public demo uses synthetic or aggregated data. Stored third-party article text is never published.

### 2. Discovery
- **RSS** where a feed exists: DOJ, InSight Crime, Zeta Tijuana, El Norte (summary only, paywalled), and Ríodoce and Animal Político once they respond.
- **Listing pages** for CBP, SEMAR and FGR.
- **GDELT DOC 2.0** for outlets without RSS (Proceso, Milenio). It also runs keyword discovery across Mexican and border-region media; results are filtered to the domains registered in `feeds.yaml`. GDELT is free for any use with a citation and link.
- **Initial Admiralty grades:** official U.S. sources A; Mexican official sources and established outlets B. Mexican official claims are self-reported and need corroboration.

### 3. Structured sources
- **OFAC SDN:** the public XML export, filtered to narcotics, TCO and SDGT programs with a Mexico or Central America nexus. Individuals appear only as attributes of designation records (hard rule 3).
- **FTO notices:** the Federal Register API, which is public and needs no key. This also clears the carried-over follow-up to check for designations after 2025-02-20.
- **SESNSP** municipal crime incidence. The files are on SharePoint with no stated licence, so automated download is verified at implementation, with a manual import fallback like CBP's FY20.
  - **There is a methodology break in 2026.** Series from before and after are stored, and labeled, separately.
- **INEGI** geography (municipalities) and the localities catalog for the gazetteer, under INEGI's free-use terms:
  - Attribution must read "Fuente: INEGI, <product>".
  - Users must be told the data has been transformed, and our analysis must never be presented as INEGI's.

### 4. AI pipeline
| Stage | Engine | Notes |
|---|---|---|
| Batch | Message Batches API | **Added 2026-11-12.** An extraction backlog of at least 25 documents (a backfill, or `make reextract` after a prompt change) is submitted as one batch at 50% price. Each request passes the same guards. Results are validated like real-time responses; a failed result gets one real-time retry, then quarantine. Sonnet stays real-time: batches cannot use the refusal fallback. |
| Relevance filter | Ollama on `127.0.0.1:11434` | A small instruct model, chosen by recall on the labeled set; the threshold is tuned for high recall. No API spend. **2026-11-11:** `gemma3:4b` at 0.2. On 33 labeled documents (14 relevant) it passed every relevant one, against about 69% weighted recall for `qwen3:4b`. It passes about 89% of documents, so Haiku's relevance check does most of the filtering, at under $0.001 per document. |
| Translation and extraction | `claude-haiku-5-5` | $0.10 / $0.50 per MTok for prompts up to 100K. Structured output via `messages.parse` / `output_config.format` with pydantic schemas. Effort `low`, raised only if the precision eval shows a gain. |
| Analysis (corroboration, conflict resolution) | `claude-sonnet-5-5` | $2 / $10 per MTok, cache reads $0.10. Only for conflicting or high-significance clusters. ICD 203 language, citing record ids. Uses the server-side refusal fallback (`fallbacks: "default"`). |

- **Prompt caching:** the shared instruction block (schema, chemical watchlist, alias table) is the cached prefix. Minimum is 512 tokens on both models; writes cost 1.25× on the 5-minute TTL. Cache-hit rate is watched through `usage.cache_read_input_tokens`.
- **Batch API** (50% cost) for backfills and the nightly backlog. Live work uses the standard endpoint.
- **Validation:** every output is parsed into a pydantic schema. Invalid output gets one retry, then goes to `llm_quarantine`.
- **Refusals:** Haiku 5.5 has **no server-side refusal fallback**, so a refusal also goes to quarantine. Nothing unvalidated reaches the core tables.
- **Ledger:** every call is logged to `llm_usage` (model, `prompt_version`, input, output and cache tokens, cost), and every derived record stores its `model` and `prompt_version`.
- **Budget:** `OSINT_LLM_MONTHLY_BUDGET_USD` defaults to $75. At 80% of the cap, the API stages pause and the UI and logs alert. Ingestion and the local filter keep running.

### 5. ACLED exclusion (from ADR 0003; lifted by ADR 0006)

*ACLED gave written consent on 2026-11-11 (ADR 0006). The check below now applies only when `acled_llm_consent` is false, and ACLED events may be sent for corroboration.*

- **The gateway** (`app/enrich/llm/client.py`) is the only code that calls Claude. It accepts input only as `Document` records, plus derived records whose provenance traces back to documents.
- **The check:** before each call it rejects any input whose source, or any linked event's source, is in a blocklist containing `acled`.
- **The analytic stage** clusters document-derived events only. ACLED events may appear in the UI next to clusters, but they are never sent.
- **Tests** prove that an ACLED-linked input raises before any request is sent.

### 6. People
Extraction schemas have **no fields for individuals**. Prompts instruct the model to describe organizations, events, places and quantities only. Named people appear in stored source text, as they appear in the article, but never become records (hard rule 3). *Amended by ADR 0005: leaders of criminal organizations identified as such by the source may be named in free-text fields.*

### 7. Geography and AOI
- **AOI:** expands to all 32 Mexican states, as phase-2 `reference_areas`.
- **ACLED filter:** widens to all of Mexico, by re-processing raw pages already on disk; no new pulls.
- **Geocoding:** uses a **local gazetteer** built from INEGI localities and municipalities. No external geocoding service is called (CLAUDE.md "Do not": no outbound calls beyond source pulls and Claude). Each result records its precision: 1 locality, 2 municipality, 3 state.
- **U.S. mentions:** geocoded only within the four border states. A named port of entry resolves to its cited `nodes` point (precision 2, `node_id` on seizures); otherwise to the state (precision 3).
- **Records outside the AOI (owner decision, 2026-11-11):** regional outlets also report on, for example, Bolivia, Colombia or Puerto Rico. These news-derived events and seizures are **stored with `in_aoi = false` and no geometry, and are hidden from feeds and the map by default**, with an opt-in filter to show them. A record counts as inside the AOI when its extracted country is Mexico, or the U.S. with a border state or no state named; an unknown country also counts as inside. Central America becomes in-AOI in Phase 4.

## Consequences
- Coverage of Spanish-language reporting depends on GDELT's recall for Proceso and Milenio, which is modest (2 Proceso hits in 3 days in the test query). RSS-native outlets carry most of the volume.
- If the owner reverses decision 1, the outlets marked "accepted risk" switch to `text: summary` in `feeds.yaml`, and their stored text is deleted.
- Four sources are `status: pending` (SEMAR, FGR, Ríodoce, Animal Político) and will be re-checked when their ingesters are built.

## Amendment (2026-11-21): extraction output as a forced tool call

**What happened.** `extract-v8`, which added persons (ADR 0013) to the UxS and electricity-theft details (ADR 0009), produced a JSON schema too large for the API's structured-output grammar. The API rejected every request with a 400 ("compiled grammar is too large"), so no v8 request ever succeeded. Batch results came back errored, and the real-time retry raised the same 400. That aborted the collect stage, so from 2026-11-21 04:15 UTC no batch was collected and 673 documents waited in `batched`. Probes on synthetic text showed `extract-v6` was close to the limit: adding persons alone, or UxS plus electricity theft together, was enough to exceed it. Removing enums or nullable unions did not bring it back under.

**Decision.**
- **Tool transport.** An output model too large for the grammar sets `llm_transport = "tool"`. The gateway then sends its schema as the input schema of one forced, non-strict tool (`record_output`, `tool_choice` set to that tool) instead of `output_config.format`. Only `Extraction` uses this. The filter and analytic stages keep strict JSON.
- **Validation is unchanged.** The pydantic model checks every response; invalid output is retried once, then quarantined. Without a grammar, the model is the only schema check, and the quarantine rate shows any drift.
- **Caching.** The tool definition sits before the cached system block, so the cache breakpoint covers it.
- **Collect stage.** A retry the API rejects as a bad request is quarantined (`reason = request_rejected`), and collection continues with the next result and batch.
- **Prompt version.** The prompt text is unchanged, but the version moves to `extract-v9` to record the transport change. The v8 batches were requeued under the existing prompt-version rule and resubmitted as one v9 batch.
- **Follow-up (same day).** The first v9 batch quarantined 114 of 673 documents, 111 of them for a missing person `title`. Two causes:
  - **Schema bug, present since v8:** `strict_schema` stripped every key named `title`, to drop pydantic's auto-generated titles. That also removed the person field named `title`, so the model was never asked for it, but pydantic required it.
  - **Fix:** the schema builder now keeps field names. Extraction's nullable and list fields default to empty, so an omission validates; the schema sent still lists every property as required.
  - **Same version:** every v9 document that named a person had failed, so no stored v9 record came from the flawed schema, and the version stays `extract-v9`.
  - **Recovery:** the 114 documents were requeued and resubmitted as one batch.

## Amendment (2026-11-22): related-story headlines removed from article text

- **What happened.** Full-text extraction kept other articles' headlines. All 73 stored Quadratín articles began with one, and 131 articles from Línea Directa, InSight Crime, DroneLife, Zeta and Aristegui had labeled related-story lines or lists. In document 1929 a stray headline became event 268299, a false domestic-violence charge against a named person.
- **Fix (`app/ingest/related.py`).** Quadratín's headline cards are pruned before extraction. Labeled related-story lines ("Te puede interesar leer:", "SEE ALSO:", "Read more:" and their lists) are removed in `upsert_document`, so page fetches and RSS bodies are both covered. Dataminr alerts are stored by their own ingester and carry no such block.
- **Correction (owner-approved, 2026-11-22).** Removed event 268299, its single-event cluster 276, person 101's "charged" status and that event link, and re-parsed document 1929's text from its saved page. Labels were not changed; label 592 still judges the deleted event. Label 592 was later deleted (owner-approved "Fix label 592", 2026-11-22): its event no longer exists, so it could not be shown or re-checked. extract-v9 record precision went from 189/211 correct to 188/210 (events 130/134 to 129/133); the overall figure moves from 89.6% to 89.5%. Label 593 (person 101) stays, since that record keeps four claims from document 1929. Backup: `data/raw/_backups/osint-before-label-592-20261123T025747Z.dump`.
- **Cleanup (owner-approved "Clean and correct", 2026-11-22).** Removed 311 stray lines from those 203 stored articles (deletion only, hashes updated, pipeline status untouched), took the borrowed text out of six summaries (documents 1520, 1538, 1559, 1650, 1705, 1981) and out of event 268053's description (marked `corrected`). Labels, person claims and all other records were not changed.
- **The first fix was incomplete.** The cleanup's dry run found wordings it missed ("No deje de leer", "Siga leyendo", "Debería leer", "Tiene que leer", "Lee", "Nota sugerida", "Sugerido", "Prodría interesarle", "Más en <section>", "Más de la LMP") and bare link paths in Infobae live blogs. All are now removed at ingest. The labels are a list, so a new wording gets through until it is added.
- **Second cleanup (owner-approved "Clean those too", 2026-11-22).** Removed 38 lines from the eight articles those forms had reached (1312, 1351, 1356, 1417, 1560, 2128, 2170, 2188) and took related-story content out of three summaries (1351, 1984, 2053). 2170 and 2188 had been sent in batch 23 before cleaning. Their texts were cleaned before collection, and review of the results found nothing taken from the removed lines.
- **Open.** Label 592 still judges the deleted event 268299.

## Amendment 2 (2026-11-22): dates are local days (owner-approved "Fix dates")

- **What was wrong.**
  - Every day derived from a report was its UTC day: the day shown to Haiku, fallback event and seizure dates, "reported on", and the day shown to Sonnet. An evening report in Mexico was dated tomorrow.
  - Haiku got no weekday, so it misread "este sábado".
  - CBP release dates were read day-first when both numbers were 12 or less (10 November became 11 October: 10 documents).
  - GDELT feeds stored the time GDELT saw the article (0.5 to 3 hours late) instead of the page's publication time.
- **Fix.**
  - CBP's month-first release date is read from the page and checked against its weekday.
  - Each active feed declares its newsroom's time zone in `feeds.yaml`, and `app/ingest/publication.py` gives the local day to every derived date. Dataminr uses Mexico City. A bare date (midnight UTC) is not converted.
  - GDELT feeds prefer the page's own timestamp when it has an offset and is not later than the time seen.
  - `published_at` stays a UTC instant.
- **Prompt (extract-v10).** The instructions are unchanged. Only the PUBLISHED line changes: local day, weekday and local time. On 64 stored articles run twice each, events dated after publication went from 13 to 0, undated events from 40 to 23, and relevance was unchanged (125 of 128 judged relevant).
- **Tested and rejected.** A line listing the previous days made Haiku judge two relevant reports irrelevant in 5 of 5 runs. A written date rule was also unstable. Re-test on repeated runs before adding either.
- **Labels and re-extraction.** The owner's labels are on extract-v9. The labeling top-up and `make eval` stay on v9 (`LABELED_VERSION`) until the owner moves them, and `make reextract` does not replace v9 records.
- **Stored dates (owner-approved "Apply A, B, D", 2026-11-22).** Applied from the reviewed list (`data/raw/_reviews/date-corrections-20261122.json`, SHA-256 `9c2f2c21d35c48250270717d31a1389359b9c3327d97f432d6beb038ed369fda`, gitignored; it holds every old value):
  - A: 24 records moved to the day the article states.
  - B: 78 records dated after their report moved to the local publication day, which is the latest possible day. Their precision was kept.
  - D: 23 publication times, 283 person-claim "reported on" dates and 44 cluster date ranges.
  - The 80 corrected events carry `date_corrected` (old day, old precision, basis). Seizures have no such field, so their old days are in the list only. Labels, cluster membership and assessments were not changed.
- **Wording (owner-approved "Fix wording", 2026-11-22).** Summaries 1540, 1560 and 1176 now give the corrected day. Assessments 6, 9 and 14 were replaced by new Sonnet assessments (30, 31, 29) made from the corrected dates.
- **Known, not changed.** The defensa.com feed sends Madrid wall time without an offset, stored as UTC: its times are an hour late (two in summer), its days are right.
- **Year (owner-approved "Remove it", 2026-11-22).** Summaries 1176 and 657 no longer put the businessman's case in 2024; their articles give that year only for the journalist's kidnapping. No year was added.
- **Assessment 21 (owner-approved "Redo it", 2026-11-22).** Replaced by assessment 32, made from the corrected summaries. It no longer attributes a 19 November date to Borderland Beat. Same incident, toll (3) and confidence; the likelihood field went from very likely to likely.
- **Group C (owner-approved "Apply all nine", 2026-11-22).**
  - Re-dated: 267866 (3 November), 268228, 268247, 268354 and 268240 (20 November), 268022 (13 May, from document 891) and 268386 (21 November 2026, the latest possible day). Each carries `date_corrected` with its basis.
  - Kept: 268071 (21 November; its article gives two accounts).
  - Split: 267866 moved from cluster 106, a different incident, to its own cluster 309.
  - Deleted: seizure 103, an embassy post about a 2025 seizure with no month, place or amount. Full row in `data/raw/_backups/osint-before-group-c-20261122T201919Z.dump`.
- **Re-extraction keeps hand corrections (owner-approved "Protect them", 2026-11-22).** `make reextract` skips a document with an annotation starting `Hand-corrected:` (`extract.mark_corrected`). The ten corrected documents it would have queued are marked: 59, 424, 489, 638, 903, 910, 933, 945, 1098, 1136. Any later hand correction must call `mark_corrected` in the same transaction.
- **All corrected documents marked (owner-approved "Mark them too", 2026-11-22).** A comparison of every backup with the live database found 121 hand-corrected documents; all are now marked, each with its correction. Moving `LABELED_VERSION` off v9 would have queued 59 of them (the rest are also labeled); with the marks it queues none.
- **Event 268354 (owner-approved "Fix event 268354", 2026-11-22).** Its location was the truck in front of the 6 de Enero primary school in Tierra y Libertad, but its description and quote were the article's sentence about a body in a burned vehicle on the waterfront, a death already counted in event 268353's four. The article reports five deaths; the description and quote now give the fifth, in the truck at the school. Location wording tidied; date, toll, type and cluster unchanged. The event carries `description_corrected`; document 1991 is marked hand-corrected. Backup: `data/raw/_backups/osint-before-event-268354-20261123T021912Z.dump`.
