# ADR 0010: Phase 3 source research — what to add, what to drop

- **Status:** Proposed (awaiting owner approval)
- **Date:** 2026-11-13
- **Decision owner:** project owner
- **Relates to:** ADR 0008 §2 and §6 (outbound calls, sources); ADR 0009 §3 (sources to research); ADR 0004 (news pipeline)

## Context
ADR 0009 named four source groups to research for unmanned systems (UxS) and electricity theft. Each was checked on 2026-11-13 against its robots.txt and published terms. Nothing has been ingested.

## Findings

| Source | robots.txt | Terms | Finding |
|---|---|---|---|
| gob.mx press listings: Guardia Nacional, Defensa (SEDENA), SSPC | No `*` group, so generic clients are allowed | [gob.mx terms](https://www.gob.mx/terminos): personal, non-commercial viewing and downloading; no public display, redistribution or transfer to third parties | **Usable.** Same terms as the SEMAR and FGR feeds already registered. Listing pages expose `/<agency>/prensa/<slug>` links. FGR's listing returned HTTP 500 on 2026-11-13; watch its ingest runs. |
| CFE bulletins (`app.cfe.mx/.../Boletines`) | `cfe.gob.mx` has none (404) | [CFE terms](https://www.cfe.gob.mx/Pages/TerminosyCondiciones.aspx): general acceptance terms, no explicit automation clause found | **Not automated.** The bulletin app sits behind bot protection (Incapsula), which counts as automated access being refused, as with SESNSP. CFE theft cases reach the dashboard through press and GDELT coverage. |
| The War Zone (twz.com) | Allows; declares `Content-Signal: ai-input=yes` | Not yet read | **Candidate.** Terms check before activation. |
| DroneDJ | Allows generic clients; blocks AI training crawlers only | Not yet read | **Candidate.** Terms check before activation. |
| El Economista (energy coverage) | Allows article paths | Not yet read | **Candidate.** Terms check before activation. |
| Energía a Debate | Disallows `ClaudeBot`, `Claude-User` and `/feed/` | — | **Excluded.** It refuses Claude agents and feed access. |
| Pixtoday.net | `Disallow: /` for every agent; site returns 403 to automated fetches | Terms not readable without signing in | **No automated access.** Only an owner-driven route is possible (see decision 4). |
| Telegram (official MTProto API) | — | [API Terms](https://core.telegram.org/api/terms) §1.5 and [content licensing](https://telegram.org/tos/content-licensing) prohibit using or aggregating platform data to deploy AI or ML, with no public-channel exception | **Excluded.** The pipeline runs every document through a local model and Claude, which those terms forbid. Unofficial-client accounts are also placed under observation. |
| Brave Search API | — | [Brave API ToS](https://api-dashboard.search.brave.com/terms-of-service) §3(b)(i): no storing, caching or databases of results beyond transient use; storage rights need a custom paid plan | **Deferred.** Incompatible with "store every raw pull", and storage rights are paid data. |
| Google Custom Search JSON API | — | Closed to new customers; discontinued 2027-01-01 | **Not viable.** |
| Bing Web Search API | — | Retired 2025-08-11 | **Not viable.** |
| GDELT DOC 2.0 | Already approved (ADR 0004) | Free for any use with citation | **Use for search.** Keyword and phrase search with `sourcelang:spanish`, a rolling 3-month window, up to 250 results per query. |

## Decision
1. **Official bulletins.** Register the Guardia Nacional, Defensa and SSPC press listings in `data/reference/feeds.yaml`, under the same handling as SEMAR and FGR: personal use, never displayed publicly or redistributed. Official claims stay self-reported and need corroboration. CFE bulletins are not automated.
2. **Trade and energy press.** The War Zone, DroneDJ and El Economista are activated only after their terms are read and recorded per feed. Energía a Debate is excluded.
3. **Search.** No paid search API now. The framework's taxonomy (§3) becomes a set of GDELT DOC queries, Spanish and English, run every 3 hours with the existing job. Brave is revisited only under a future paid-data ADR that buys storage rights.
4. **Pixtoday.net.** No automated collection: its robots.txt disallows everything. Two owner-driven options remain, chosen after the owner reads its terms while signed in:
   - the owner saves items they select and imports them with a manual file import (`make ingest SOURCE=pixtoday FILE=path`), as for SESNSP;
   - or the owner gets written permission from the operator for automated access, recorded in a follow-up ADR, as ACLED's was in ADR 0006.

   Either way the terms must permit storage and AI processing, or Pixtoday items stay out of the pipeline.
5. **Telegram.** Not collected. Its terms prohibit the AI processing the pipeline depends on. Cartel claims first published on Telegram still reach the dashboard when press outlets report them, graded by the reporting outlet.
6. **Outbound allowlist.** The first new host added under this ADR comes with the config allowlist that ADR 0008 §2 requires, listing every destination in `docs/data-sources.md`.

## Consequences
- Phase 3 adds no social media and no paid service. Coverage of cartel drone footage depends on press reporting it, which lowers recall for the earliest, single-source claims.
- PLAN.md's Telegram and search-API rows change to "excluded" and "GDELT taxonomy queries".
- Pixtoday.net stays open until the owner reads its terms.
- Each new feed still gets a fixture test and an entry in `feeds.yaml` with its terms note.
