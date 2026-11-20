# ADR 0007: Priority focus on human smuggling and threats to the border

- **Status:** Accepted
- **Date:** 2026-11-12
- **Decision owner:** project owner
- **Relates to:** PLAN.md intelligence requirements; CLAUDE.md hard rule 4; ADR 0004 (AI pipeline)

## Context
Phase 2 extracts every kind of organized-crime event from news across Mexico. The owner asked for a hyper-focus on two topics:
- **human smuggling**
- **threats to the border:** criminal drone (UAS) incursions, laser strikes, gunfire, and similar

Both show up in the existing sources: CBP and DOJ releases, and border-region outlets. No new source is added.

## Decision
1. **Relevance:** the local filter (`filter-v2`) and the extraction prompt (`extract-v4`, refined in `extract-v5`) treat these topics as top priority. The extraction prompt also counts as relevant:
   - border-security policy
   - binational cooperation against trafficking
   - official enforcement statistics

   Such articles add context. They produce events only where criminal activity is described.
2. **Structured category:** a news-derived event may carry `events.border_threat`, one of:
   - `human_smuggling`: smuggling loads, stash houses, smuggling deaths, smuggling organizations and their prosecution
   - `uas_incursion`: criminal drones crossing or operating at the border
   - `laser_strike`: lasers aimed at aircraft or border personnel
   - `gunfire`: shots fired at or across the border
   - `assault_on_personnel`: attacks on border officers or soldiers
   - `tunnel`: cross-border tunnels
   - `other_border_threat`

   The feed, event API and map can filter on it. Other events have `NULL`.
3. **Threat activity only (hard rule 4).** Threat events describe:
   - what the criminal actors did
   - where it happened, at the precision the source reports (city, municipality or port), never finer
   - when it happened
   - the outcome

   Extraction never records:
   - the number, units, equipment, positions, patrol patterns or response tactics of U.S. or Mexican personnel
   - sensor, camera or tower locations
   - any detail whose purpose is to describe friendly forces

   The dashboard offers no view that compiles or maps friendly-force activity. Releases that only describe U.S. or Mexican law-enforcement operations, deployments, closures or training produce no events.

## Consequences
- **Measured relevance:** the extraction prompt's relevance decision was tested in a dry run (`make eval HAIKU=1`) on 43 owner-labeled documents:

  | Prompt | Recall | Precision | Main change |
  |---|---:|---:|---|
  | `extract-v3` | 87.5% | 63.6% | — |
  | `extract-v4` | 87.5% | 73.7% | border-threat priority |
  | `extract-v5` | 100% | 94.1% | South America and the Caribbean out unless tied to the region; border-crossing developments in as context only |

  `extract-v5` was tuned on these same documents, so its figures must be confirmed on newly labeled ones.
- **Earlier extractions:** documents extracted under `extract-v3` have no `border_threat`. Unlabeled documents are re-extracted through the Batch API. Documents the owner has already labeled keep their `extract-v3` records, so those labels stay valid.
- **Precision:** the evaluation measures the new field like any other. `border_threat` is a labelable field on the labeling page.
- **Proximity to friendly forces:** a map of attacks on border personnel sits close to friendly-force data. The precision limit and the exclusions above keep it threat-focused. Any later feature in this area needs a check against hard rule 4.
