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
