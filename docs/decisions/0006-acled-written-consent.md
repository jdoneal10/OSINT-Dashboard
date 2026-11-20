# ADR 0006: ACLED written consent for Claude processing and professional use

- **Status:** Accepted
- **Date:** 2026-11-11
- **Decision owner:** project owner
- **Amends:** ADR 0003 (ACLED licence and handling), ADR 0004 §5 (ACLED exclusion), CLAUDE.md hard rule 5

## Context
ADR 0003 recorded the ACLED EULA terms for a personal, non-commercial licence. Two of them shaped Phase 2:
- **s.7.1:** no ACLED content as LLM input without ACLED's written consent. The Claude gateway enforced this.
- **s.3.1:** external material must be transformative, so screenshots and demos had to use synthetic or aggregated data.

## Decision
On **11 November 2026** ACLED's administration team gave the owner **written consent** by email. The email stays private: the owner keeps it, and it is not committed here. In summary, it says:

1. **Claude processing is allowed.** ACLED data may be processed with Claude for this project, given its professional nature. That includes corroborating news reports against ACLED events.
2. **Professional use of the dashboard is allowed**, on two conditions:
   - the owner does not profit from it in any way;
   - the data is clearly attributed to ACLED.

### What changes
- **The gateway** (`app/enrich/llm/client.py`) no longer refuses ACLED-derived input.
  - This is controlled by the setting `acled_llm_consent` (`OSINT_ACLED_LLM_CONSENT`), which defaults to `true`.
  - Setting it to `false` restores the full refusal, for example if consent is withdrawn.
  - The provenance requirement stays: every call must declare its source records.
- **The dashboard and screenshots** showing ACLED-derived views may be shown in professional settings, such as a portfolio or an interview. Every visual keeps its attribution: the ACLED name and link, the access date, and the filters applied.

### What does not change
- No profit or commercial use, in any form.
- Raw ACLED data is not redistributed. No export, no published database, and `data/raw/` is never committed (CLAUDE.md "Do not").
- API access only; no scraping.
- Usage records are kept for 3 years (EULA s.15).
- Only Claude is covered. Any other model or service receiving ACLED data needs a new decision.

## Consequences
- **Corroboration against ACLED (built 2026-11-12):**
  - Clustering attaches at most one matching ACLED event to a news cluster. A match needs the same INEGI municipality as a news event geocoded to municipality level or finer, an event date within ±1 day, and a compatible event type. The best candidate is the closest date, then the closest fatality count.
  - The ACLED event counts as one more independent source in the cluster's Admiralty grade. Its fatality count can raise a conflict, which sends the cluster to Sonnet.
  - Sonnet sees the ACLED record as `[acled event N]` and may cite it. Its prompt notes that ACLED may code from the same articles, so agreement is not fully independent.
  - The UI marks such reports "ACLED-corroborated" and shows ACLED attribution beside them.
  - ACLED never creates a cluster on its own.
- **ACLED's release delay:** the owner's ACLED access releases events about 12 months late. The newest event was 2025-11-12 when checked on 2026-11-12. A current report can therefore only be corroborated about a year later, so clusters stay matchable for 400 days. Until then, corroboration of recent reporting rests on news sources alone.
- Any ACLED-derived prompt is logged in `llm_usage` and carries record ids, like every other LLM call.
- If ACLED narrows or withdraws consent, set the switch to `false`, update this ADR and review any ACLED-derived assessments.
