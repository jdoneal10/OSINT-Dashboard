# ADR 0011: ACLED weekly aggregates and the strategic-competition dataset

- **Status:** Accepted (2026-11-16)
- **Date:** 2026-11-16
- **Decision owner:** project owner
- **Relates to:** ADR 0006 (ACLED consent), ADR 0008 (hard rules), ADR 0009 (UxS focus), ADR 0010 (Pixtoday)

## Context
On 2026-11-16 the owner supplied two files they downloaded by hand while signed in:
1. `Latin-America-the-Caribbean_aggregated_data_up_to_week_of-<date>.xlsx`: ACLED's published weekly aggregates.
2. `StrategicCompetition_<date>.xlsx`: Chinese, Russian and Iranian sites and projects in Mexico and Central America, updated 2026-11-14.

Both were profiled locally. A case-sensitive scan for control markings (FOUO, CUI, LES, NOFORN, classification words) found none. Both carry Microsoft Purview label metadata from the owner's personal Microsoft 365 tenant (confirmed by the owner on 2026-11-16), not from a work or government system. Nothing has been ingested.

## Findings

### ACLED weekly aggregates
- **Content:** 6,451 rows, one per week × admin1 × event sub-type, from 2025-11-01 to 2026-10-31. Columns: event count, fatalities, population exposure, disorder type, and an admin1 centroid. Countries: Mexico (4,737 rows), Honduras, Guatemala, Panama, Costa Rica.
- **Value:** it covers the ~12-month release lag of the owner's event-level access (ADR 0006), as counts per state, not as events.
- **Terms:** ACLED data under the owner's account and ADR 0006's written consent: Claude processing allowed, professional non-profit display with attribution, no raw redistribution. ADR 0006 says "API access only". This ADR records a manual download of ACLED's own published aggregate file as an allowed access path; it is not scraping.

### Strategic competition
- **Content:** 579 site records. China 497, Russia 67, Iran 15. Mexico 293, Panama 105, Nicaragua 91, Costa Rica 51, Honduras 22, Guatemala 17. Categories: commerce, ICT, transportation (30 ports), society and culture, energy, mining, military and security (23), politics, space and others. Each row has coordinates, status, dates, costs, owning companies and up to 11 cited sources (Pixtoday, ASPI, Reuters, the Federal Register, USCC and others).
- **People:** none as records. Actors are governments, state-owned enterprises, proxies and companies. Addresses are of businesses and installations, not people.
- **Relevance to the TCO mission:**
  - **Precursors (Phase 4):** Chinese-operated ports and logistics (Manzanillo, Lázaro Cárdenas, Panama) sit on the precursor routes.
  - **UxS (ADR 0009):** DJI and Autel retail, distribution and manufacturing sites are the commercial drone supply that cartels adapt.
  - **Context:** Chinese overseas police stations and private security firms, and Russian presence in Nicaragua, are state activity, not TCO activity.
- **Scope:** most of the dataset is state-actor activity. CLAUDE.md scopes the project to TCOs, so using it widens scope.
- **Rule 4:** some military and security rows describe partner-nation security facilities, for example a Costa Rican police academy and a Mexico City police unit's office receiving Chinese training or equipment. Those reveal partner capabilities and locations.

## Decision
1. **ACLED aggregates.**
   - Load into a new `acled_weekly_admin1` table with `make ingest SOURCE=acled-weekly FILE=path`. The raw file goes to `data/raw/acled-weekly/<date>/` and is never committed. Re-imports upsert on week, admin1 and sub-event type.
   - **One continuous ACLED series (owner decision, 2026-11-16).** ACLED's historical events are rolled up to the same grain (ACLED week, Saturday to Friday, × admin1 × sub-event type) and joined with the aggregates in one view. Each week takes its counts from one source only: event-level counts up to the last week the event data fully covers, aggregates after that. Each row records which source it came from.
   - Trend charts, state choropleths and share-of-flow measures read that combined series, so ACLED history runs to 2026-10-31 without a gap. Admin1 names in the file are matched to the INEGI and Central American admin1 codes the events already use; an unmatched name fails the import.
   - **What it cannot do:** the aggregates have no individual events. They add nothing to the event map, the event list, clustering or news corroboration, which stay event-level. Where the UI shows the combined series, it notes that recent weeks are ACLED aggregates and keeps ACLED attribution.
   - When ACLED releases event-level data for a week, those events take over that week's counts. History is kept: each aggregate import is stored as a dated snapshot, as for CBP.
2. **Strategic competition: a context layer, not a tracked actor set.**
   - Load into a `strategic_sites` reference table, each row keeping its citations (rule 2), with `make ingest SOURCE=strategic FILE=path`.
   - Shown as an optional map layer and joined to Phase 4 precursor-route and UxS views. No alerts, no scoring and no INTSUM sections about state actors.
   - **Rule 4 filter:** rows whose site is a Mexican or Central American partner government's security or police facility are dropped. Foreign-state and company sites (Russian installations, Rosoboronexport, Chinese security firms and overseas police stations) are kept. Nicaragua is not treated as a partner; the owner may override this.
   - Pixtoday-sourced rows follow ADR 0010's permission, which covers Claude processing.
3. **Phasing.** The ACLED aggregates can be built now, as a Phase 2 follow-up. The strategic layer lands with Phase 4 (precursors and routes), since that is where it connects to TCO activity.

## Consequences
- ACLED trends run continuously from the historical events into the last year, at state level. Point-level detail for that year still waits for ACLED's event release.
- The project's map gains a state-actor context layer. It stays secondary to TCO tracking; widening to strategic competition as a mission would need its own ADR.
- Rule 4 costs a few military and security rows.
