# ADR 0014: Energy interaction: reported grid interactions, indicators and municipal assessments

- **Status:** Accepted by the owner, 2026-11-22 (see Owner decisions). Built: schema (step 2), the ACLED pass (step 5) and prompt `extract-v11` (step 4, tested; not yet live).
- **Relates to:** ADR 0008 (hard rules), ADR 0009 (UxS and electricity-theft focus), ADR 0012
  (critical-infrastructure keep rule), owner framework `docs/framework/uxs-and-electricity-theft.md` §2.

## Context
IR 9 asks which criminal organizations steal electricity, how, to power what, where and at what
scale. After the extract-v10 re-extraction (2026-11-22) the database holds **zero** electricity-theft
events:

- Rule 12 of the extraction prompt fires only when an article reports theft outright (a raid,
  investigation, prosecution or official statement). None of the 2,609 stored news documents uses
  "robo de energía", "diablito" or "conexión clandestina".
- The news corpus is young: 2,535 of those documents are from the last 11 days.
- Related reporting exists but is discarded. ACLED holds about 1,292 events since 2018 that
  mention electricity infrastructure (74 in 2018, 237 in 2025). Most are service protests, but
  about 94 have a criminal or armed link: groups cutting power during roadblocks, attacks on and
  kidnappings of CFE workers, a kidnapping at a substation, clashes over infrastructure.
- Theft is seldom named as such. The analytically useful signal is a pattern of reports (seized
  mining rigs, a lit grow, repeated outages where a group operates, CFE withdrawing from an area)
  that together support an inference.

The framework's scope limit stays: the dashboard does not find suspect sites from utility data and
does not flag private properties by inference.

## Decision (proposed)
Three layers, built in order. Each layer is stored and shown under its own label, so a reader can
always tell reported fact from indicator from assessment.

### Layer 1: reported grid interactions (widen the direct record)
Rename the concept from "electricity theft" to **criminal interaction with the electrical grid**,
with theft as one kind. A new `grid_interaction` value on the event (alongside the existing
`energy_theft` detail, which is kept unchanged for theft cases):

| Kind | Example reporting |
|---|---|
| `theft` | the current rule 12 cases, plus illegal hookups described in other words ("se colgaban de la red", "toma ilegal de luz") |
| `deliberate_outage_or_sabotage` | a group cuts power, burns a substation or downs towers, e.g. during a roadblock |
| `attack_on_utility_workers` | CFE crews attacked, kidnapped or threatened (workers are victims: recorded by role, never as persons) |
| `extortion_or_service_control` | a group charges for, rations or controls power in a community; extortion of the utility or contractors |
| `infrastructure_theft` | transformer, cable or copper theft **where the source links it to a criminal group** |
| `utility_withdrawal` | CFE or contractors suspend work or service in an area citing insecurity |

Rules carried over from rule 12: report the case only; facilitator by role only; scale as reported,
never estimated; household diablitos with no criminal link stay out of scope; huachicol is not
electricity.

**ACLED:** ACLED events are not run through extraction today. A separate pass would classify the
~1,292 electricity-related ACLED notes into the same `grid_interaction` kinds (Haiku through the
Batch API, permitted by ADR 0006; estimated well under $1). ACLED attribution stays on every view.

### Layer 2: indicators (reported facts that suggest theft without claiming it)
A new `energy_indicator` value, set only from what the text reports:

| Indicator | Example |
|---|---|
| `mining_equipment_seized` | crypto-mining rigs found in a raid or seizure |
| `high_load_site` | an indoor grow, lab or compound reported with heavy electrical equipment (lights, AC, generators, refrigeration) |
| `outage_in_contested_area` | repeated or unexplained outages the source places where a group operates |
| `utility_insider_reported` | a utility employee reported as linked to a group, without a theft claim |
| `fuel_theft` | fuel theft by a criminal group (pipeline taps, huachicol); not fuel smuggling. Added by the owner: the networks that tap pipelines also tap the grid |

Indicators are labeled "indicator, not a theft claim" in the UI and never set `energy_theft`.

### Layer 3: municipal assessments (analysis, labeled as such)
A new analytic job, in the pattern of the existing Sonnet corroboration stage (`app/enrich/analyze.py`):

- **Trigger:** a municipality with two or more Layer 1 or Layer 2 records from at least two
  independent sources in a rolling window (proposed: 12 months).
- **Output:** a short assessment in ICD 203 estimative language, for example "it is likely that
  criminal groups in [municipality] are stealing electricity", citing every record it rests on.
  Assessments that cite anything not provided are quarantined, as today.
- **Unit of analysis is the municipality.** It never names, locates or ranks a property, address
  or account, which keeps it inside the framework's scope limit.
- Shown on the electricity panel as an assessment, with its confidence and the date it was made;
  the owner can dismiss one.

## How it is built and tested
1. **Owner sign-off** on this ADR and on a matching update to framework §2 (the indicator list and
   the trigger in Layer 3 are owner judgment and must be written there as such).
2. **Schema:** a migration adding `grid_interaction` and `energy_indicator` to `events`, with
   check constraints like the existing energy columns. Mining equipment found in a seizure becomes
   a seizure item as well as an indicator.
3. **Filter:** add the Layer 1 and 2 terms to the critical-infrastructure keep rule (`infra-v3`)
   and to `filter-v3`'s topic list, so these articles reach extraction. The keep rule already passes
   "energy asset plus criminal signal" articles.
4. **Prompt `extract-v11`:** rule 12 rewritten for Layers 1 and 2. Because past prompt additions
   caused relevance regressions, v11 is run three times over a fixed set of stored documents
   (the 100 labeled ones plus a set chosen for grid content) and compared with v10 before it
   replaces it. Only then does `make reextract` run (Batch API).
5. **ACLED pass** for Layer 1 and the indicators, with fixture tests on synthetic notes. Runs
   before step 4 (owner decision 4).
6. **Labeling:** new label fields for `grid_interaction` and `energy_indicator`; the Phase 3 exit
   criterion (≥ 85% precision over 50 labeled UxS/energy records) then counts these records.
7. **Layer 3** only after Layers 1 and 2 have labeled precision at or above the target, because an
   assessment is only as good as the records under it.
8. **Panel:** the electricity-theft panel shows three tabs (reported, indicators, assessments).

## Out of scope / needs a separate decision
- **New sources** (CFE press releases, energy-regulator bulletins, state utility news). Each needs
  the owner's ask, a terms check, a `data-sources.md` row and an outbound-allowlist entry first.
  Without them, coverage of Layer 1 theft cases will stay thin outside ACLED.
- Utility-account, feeder, thermal or network data of any kind (rule 1 and the scope limit).
- Any per-property or per-account ranking.

## Consequences
- IR 9 becomes answerable from records that exist today (ACLED) instead of from a category that
  is currently empty.
- Wider rules raise the risk of false positives: copper theft by petty thieves, service protests,
  ordinary outages. The criminal-link requirement and labeling are the guard.
- A Layer 3 assessment is an inference. It is shown as one and is never stored or displayed as a
  sourced fact (hard rule 2).

## Owner decisions (2026-11-22)
1. **Frame:** IR 9 becomes criminal interaction with the electrical grid, with theft as one kind.
   All six kinds sit under IR 9; there is no separate critical-infrastructure IR.
2. **Indicators:** all four proposed indicators are kept, and the owner added `fuel_theft`
   (fuel theft only, not smuggling; rationale: same networks). Fuel theft stays out of
   `energy_theft`, as rule 12 already says.
3. **Layer 3 trigger:** two or more layer 1 or 2 records from at least two independent sources in
   a rolling 12 months.
4. **Order:** the ACLED pass runs **before** extract-v11, so its results give the historical base
   and help test the v11 rules.

## Progress
- 2026-11-22: framework §2 updated; migration 0017 adds `events.grid_interaction` and
  `events.energy_indicators` with check constraints (theft detail set exactly when the kind is
  `theft`). Extraction stores a theft case as `theft`; the other kinds and indicators wait for
  the ACLED pass and extract-v11.
- 2026-11-22: ACLED pass built (`app/enrich/acled_grid.py`, pipeline stage `grid`, prompt
  `grid-v3`). ACLED events whose notes mention the grid, utility crews, cable theft or fuel
  theft (2,359 at the start) go to Haiku one per request; the verdict is stored on the event and
  its provenance (model, prompt version, tokens, notes hash, evidence quote) in
  `grid_classifications` (migration 0018). A quote not found in the note is quarantined. An
  ACLED edit to a note queues the event again; an edit that drops the grid terms clears the
  verdict. Before the full run, 50 real-time samples were checked by hand: two prompt fixes
  followed (an outage indicator needs an area, not one house; fuel thieves named as actors
  count as fuel theft). The full run was submitted as two batches.
- 2026-11-22, results: 2,359 events classified for $0.10; 69 carry a grid-interaction kind
  (45 deliberate outage or sabotage, 19 attacks on utility workers, 4 extortion or service
  control, 1 infrastructure theft; none is a theft case) and 362 carry indicators (313 fuel
  theft, 49 area outages). The quote check was widened to accept the ACLED actors line, ellipses
  and stray brackets (each fragment must still be verbatim); one event stays quarantined because
  the model's quote exceeds 200 characters. Not yet measured: precision. A random check of 12
  kinds found one error (rioters holding a CFE worker during a price protest, tagged as an
  attack), which the owner's labels should decide before any prompt change.
- 2026-11-23: prompt `extract-v11` written. Rule 12 becomes `grid_interaction` (the six kinds,
  with the criminal-link requirement and the "not kinds" list from the ACLED pass); rule 13 adds
  the five indicators; crypto-mining equipment becomes a seizure item. The kinds and
  indicators are defined once in `app/enrich/extract.py` and shared with the ACLED pass.
  Storage keeps the theft detail exactly when the kind is `theft`: a named non-theft kind drops
  a stray detail, a detail with no kind is a theft case (as in v10), and a theft kind with no
  detail is kept with method unknown.
- 2026-11-23, test (step 4): v10 and v11 were each run three times over a fixed set of 162
  stored documents: the 101 labeled extract-v9 documents and 64 news documents with grid or
  fuel-theft terms (3 overlap; most of the 64 are ordinary outages and crashes, which serve as
  negatives). Dry runs: nothing stored, 1,480 calls including retries, $0.95.
  - Round 1 found three misreadings repeated across runs: a truck fire set by armed men that
    cut power tagged as sabotage; a lab and greenhouse raid tagged `high_load_site` with no
    electrical equipment in the text; "huachicol fiscal" (fuel smuggling and tax fraud) tagged
    fuel theft. The rules for sabotage (the grid must be the target), `high_load_site` (the
    equipment must be named) and `fuel_theft` (not tax fraud) were tightened and v11 run three
    more times.
  - Round 2 against v10: no relevance flips on the 101 labeled documents (301 of 301 calls
    relevant under both) and no document with mixed relevance across runs. Events per call
    1.30 (v10) and 1.37 (v11): v11 records events v10 missed in two articles (zero events in
    all three v10 runs) and splits detentions from a clash in one. On the grid set one document
    became relevant in all three runs: a leak from an illegal pipeline tap.
  - Grid outputs: fuel theft on five documents, consistent across runs on three; the
    `high_load_site` and fuel-smuggling errors are gone. One known error remains, 3 of 3 runs:
    the Los Mochis truck fire (document 1941) is still tagged `deliberate_outage_or_sabotage`;
    `huachicol hormiga` (small-scale fuel smuggling) was tagged fuel theft in 1 of 3 runs. The
    corpus holds no electricity-theft article, so the theft kind is untested on news.
  - Not yet done: switching the worker to v11, `make reextract`, and labeling (step 6), which
    are the owner's to approve.
