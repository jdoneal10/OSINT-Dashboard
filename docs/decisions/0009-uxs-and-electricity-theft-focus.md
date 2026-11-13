# ADR 0009: Top priority on unmanned systems and electricity theft

- **Status:** Accepted
- **Date:** 2026-11-13
- **Decision owner:** project owner
- **Amends:** ADR 0007 (border-threat focus); PLAN.md IRs and roadmap
- **Relates to:** ADR 0008 (revised hard rules); `docs/framework/uxs-and-electricity-theft.md`

## Context
The owner set two border-security topics as the new main focus:
- **unmanned systems (UxS):** cartel use, procurement, training, facilitation and employment of drones, UGVs and USVs;
- **electricity theft:** cartel energy theft and the criminal activity it powers.

The owner's notes are condensed into an owner framework, labeled as judgment rather than fact.

## Decision
1. **Priority tiers.** Relevance and extraction rank topics in three tiers:
   1. UxS and electricity theft (new);
   2. human smuggling and the other border threats of ADR 0007;
   3. everything else in scope.

   ADR 0007 stays in force, and its labels and the `border_threat` field remain valid.
2. **Roadmap.**
   - Phase 2 closes on its existing exit criteria, using the current prompts so the 100-label test measures a stable prompt.
   - **Phase 3 becomes "UxS, electricity theft and people":** new categories, person records under ADR 0008, and new sources.
   - Precursors and routes move to Phase 4; Central America, alerts and INTSUM move to Phase 5; polish moves to Phase 6.
3. **Sources to research first.** Each one gets a terms check and its own ADR before anything is ingested:
   - official bulletins (CFE, FGR, Guardia Nacional, SEDENA and SEMAR), Mexican energy press, and drone and defense trade press;
   - Pixtoday.net, through the owner's account;
   - public Telegram channels, through the official API;
   - a sanctioned search API that runs the framework's taxonomy queries.
4. **Electricity-theft scope.** The dashboard tracks reported cases only. It does not find suspect sites from utility, thermal or network data (ADR 0008 rule 1; framework §2).

## Consequences
- Phase 3 adds a new prompt version (`extract-v6`) and filter version (`filter-v3`). Documents are re-extracted through the Batch API, and labels made under earlier versions stay valid for their own records.
- New categorical fields need labeling coverage before precision on them can be claimed.
- Phase 3 is the first phase to record people. Its exit criteria include a measured check of the person safeguards.
