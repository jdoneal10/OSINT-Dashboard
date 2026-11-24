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

## Amendment 1 (2026-11-23): ACLED UxS pass, UxS labeling, and separate Phase 3 gates

Owner decisions (2026-11-23): "ACLED pass + page" and "Separate gates".

**Context.** Only 8 news events carried UxS fields (all `extract-v9`). Re-extraction under
`extract-v11` found none in the 12 newer articles that mention drones: each one was about
police, military or U.S. drones, which hard rule 4 keeps out. ACLED notes held 315 drone
mentions (2018–2025, mostly 2023–2025), but ACLED events never go through extraction, so they
carried no UxS fields. The Phase 3 sample also mixed UxS and energy: after grid labeling
(ADR 0014 step 6), 50 ACLED grid labels could have passed the gate with no UxS record labeled.

**Decision.**
1. **ACLED UxS pass** (`app.enrich.acled_uxs`, pipeline stage `uxs`), built on the ADR 0014
   grid pass and sharing its note helpers (`app.enrich.acled_notes`). Haiku reads one ACLED
   note at a time (with ACLED's actors) whose text mentions drones or other unmanned systems,
   and fills the same fields news extraction fills: `uxs_activity`, `uxs_platform`,
   `uxs_missions`, `uxs_payloads`.
   - **Criminal only.** The note, or ACLED's actors, must tie the system to criminal or armed
     actors. Drones of police, the military, the National Guard or any government are never
     recorded (hard rule 4). A criminal drone attack on security forces is recorded as a
     mission (`attack`, `surveillance_of_security_forces`) and nothing more.
   - **One event, one record.** Drone use the note says is coded as another event, or gives
     only as context (people fleeing, a protest), is left to that event.
   - **Quoted and versioned.** The model quotes the note; a quote not in the note is
     quarantined. `uxs_classifications` keeps model, prompt version, tokens and the hash of the
     notes, so an ACLED edit queues the event again.
   - ACLED's written consent covers Claude processing (ADR 0006).
2. **UxS labeling** (`uxs_labels`, page `/labeling/uxs`), built like grid labeling: one label
   per event (ACLED or news) on its UxS fields only. Verdicts: correct; partly wrong, naming
   the activity, the platform, or the missions or payloads that are wrong; wrong (no criminal
   unmanned system at all). The verdict judged is frozen on the label, and a label whose event
   was reclassified since is stale and left out. The review interleaves activities in stable
   hash order, so seizures, procurement, training and prosecutions come up before the long run
   of drone attacks. Re-extraction skips documents whose events carry a UxS label.
3. **Separate Phase 3 gates.** UxS and energy are two samples, and each needs 50 labeled
   records at ≥ 85% strict precision (plus zero person-safeguard violations).
   - UxS sample: UxS labels plus record labels on UxS events.
   - Energy sample: grid labels plus record labels on electricity-theft events.
   - A topic label replaces an event's record label in that sample. A partly wrong record
     label counts against a topic only if it names that topic's field (`uxs` or
     `energy_theft`), since the gate measures "precision on the new fields" (PLAN.md).

**Prompt development** (ACLED notes, real-time samples of 20):
- `uxs-v1`: a displacement event that cited drone attacks "coded separately" was recorded as
  drone use, double-counting the attack.
- `uxs-v2`: fixed that, but dropped seizures where only ACLED's actors (for example
  "Unidentified Gang") tied the drones to a group.
- `uxs-v3`: ACLED's actors count as the link. The pattern stopped matching "UAS", which in
  Sinaloa notes is the Autonomous University of Sinaloa.
- `uxs-v4` (after the first full batch): a crewed semi-submersible (people arrested aboard)
  had been recorded as an uncrewed boat, and explosives "made to be launched from drones"
  were recorded as seizures in some notes and not in others. Crewed craft are now excluded;
  drone-launched explosives seized or defused count as `recovery_or_seizure`.

**Consequences.**
- The UxS panels (IR 8) now include ACLED-derived events, shown with ACLED attribution like the
  grid-pass events. Platform is mostly `unknown`: ACLED notes rarely name the drone type.
- Precision only: the labels judge events that carry UxS fields, so missed drone reporting
  (recall) is not measured.
