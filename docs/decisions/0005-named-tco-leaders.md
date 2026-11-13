# ADR 0005: Naming reported criminal-organization leaders in news-derived text

- **Status:** Superseded by ADR 0008 (2026-11-13)
- **Date:** 2026-11-11
- **Decision owner:** project owner
- **Amends:** CLAUDE.md hard rule 3; ADR 0004 §6

## Context
Hard rule 3 allowed people's names only inside public indictments, designations and sanctions records. Extraction prompt `extract-v1` forbade names everywhere, but the model still named a cartel leader in one summary ("alleged CJNG leader … known as R2"). Leadership is analytically significant: arrests, deaths and successions of leaders drive fragmentation and violence. Open-source reporting names these leaders routinely, and an analyst needs to know which leader a report concerns.

## Decision
1. **Who may be named:** a person whom the open source itself identifies as a leader of a criminal organization (for example, a cartel head, plaza boss or faction leader). The name and alias are used exactly as the source gives them. No other individual is named: victims, bystanders, relatives, low-level suspects, defendants not described as leaders, journalists, and public officials are described by role (e.g. "Mexico's Security Secretary", "two victims").
2. **Where:** only in the free text of news-derived records: `documents.translated_text` (English summary), `events.description`, and the evidence quote.
3. **What stays prohibited:**
   - no person table, structured person field, or person-to-organization link;
   - no search, filter or view centred on a person;
   - no aggregation of a person's mentions across records.

   Perpetrator and target fields remain organizations only.
4. **Enforcement:** extraction prompt `extract-v3` states the rule. The labeling page has a `person_named` field, so the Step 6 evaluation measures violations: a non-leader named, or a leader named outside the allowed fields.

## Consequences
- Summaries can say which leader a report concerns, which supports later succession and fragmentation analysis without building person records.
- Names of reported leaders reach the Claude API only as part of public article text. That was already the case, because the full article is the input.
- Whether someone is a "leader" rests on the source's own characterization. The source's Admiralty grade carries that uncertainty. The UI does not present it as a confirmed fact.
