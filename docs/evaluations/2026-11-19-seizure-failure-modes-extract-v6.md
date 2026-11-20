# Seizure failure modes in extract-v5, and the extract-v6 changes

- **Date:** 2026-11-19
- **Input:** the 11 seizure records flagged in `2026-11-19-extraction-extract-v5.md` (5 wrong, 6 partly wrong; 31 of 42 correct, 73.8% strict).
- **Method:** the owner's labels (verdict and field) read locally, against each record's stored values and its source document. The owner left no notes on these labels, so the causes below are inferred from the source text and are hypotheses. Labels, notes and article text stay local. This note holds record ids and categories only.

## Failure modes

| Mode | Records | What went wrong (inferred) |
|---|---|---|
| A. Not a seizure | 57, 82 (wrong) | Goods taken earlier and sold at auction, and counterfeit-trademark goods with no smuggling or criminal-group link, were recorded as seizures. |
| B. Vague drug, vague amount | 78, 79, 80 (partly wrong) | Short alerts about "packages" of an unnamed substance. The records used three different free-text names ("unspecified illicit substance", "suspected narcotics", "alleged illicit substance"). Package counts were stored as `units` or dropped, because the unit list had no `packages`. |
| C. Mixed load in one record | 70 (partly wrong, quantity) | A rifle seized with two loaded magazines became one "weapons, 1 unit" record. A Del Rio release in the same sample split items into separate records, and the owner marked those records correct (85–87). |
| D. Contraband goods named loosely | 63 (partly wrong, substance) | A port seizure of contraband cigarettes was recorded as plain "cigarettes". |
| E. Priority, not extraction | 88 (partly wrong, quantity); 91, 92, 97 (wrong) | The stored values match the source text. The owner confirmed on 2026-11-19 that these drug amounts are too small to matter: 0.5 kg and 8 kg in Sinaloa, 1.1 lb at Del Rio, 2 kg in Coahuila. The weapons records seized alongside them were marked correct. |

## extract-v6 changes (seizures only; event rules unchanged)

- **Rule 5 rewritten, plus SEIZURE RULES S1–S6** in the cached system block:
  - **S1 scope:** auctions, forfeiture and destruction of goods seized earlier are not seizures. Neither are counterfeit goods, nor vehicles, property or jewelry taken from suspects. Contraband smuggled through a port or crossing is recorded as `contraband <goods>`.
  - **S2:** one record per item category. A mixed load is split into drugs (each on its own), firearms, ammunition, magazines, explosives, cash and precursors, and different items are never added into one total.
  - **S3:** a fixed SEIZURE SUBSTANCES list. Street and Spanish names are translated. An unnamed drug is recorded as `unidentified drug`, and "alleged" or "suspected" never appears in `substance`.
  - **S4:** precursor chemicals and finished drugs are kept apart.
  - **S5:** quantity and unit rules. A stated weight wins over a package count. Package counts go in the new `packages` unit, and "several packages" gets a null quantity. Tons convert to kg and ounces to lb, with no metric/imperial conversion. Spanish numbers and Spanish thousands and decimal separators are read correctly, and a quantity is never invented.
  - **S6:** `seizure_date` is the day of the seizure, not the day it was announced.
- **Schema:** the `unit` list gains `packages` and `doses`. Field descriptions point to the rules.
- **Storage:** `canonical_substance()` lower-cases each substance, strips hedge words, maps synonyms such as "cristal" to methamphetamine and "weapons" to firearms, and folds vague drug wording into `unidentified drug`. It applies to every extraction, including outputs that ignore the prompt. Precursor names are never folded into a drug.

## Expected effect

If the inferred causes are right, modes A–D account for 7 of the 11 flagged records. That would lift seizure strict precision on a comparable sample from 73.8% toward about 85–90%, and it would also make `substance` totals add up across documents. The estimate is unverified: the flagged records' documents carry labels, so `make reextract` skips them by design. Measuring v6 takes fresh labels on newly extracted documents, or a dry run over the flagged documents with nothing stored. Mode E is handled by priority, not by the prompt (next section).

## Re-extraction cost (not run; needs the owner's yes)

`make reextract` would queue 715 unlabeled documents (extracted or filtered out under v3 or v5). At v5's batch average of about $0.0002 per document, plus a longer cached system block, the cost is roughly **$0.15–0.40** through the Batch API. Month-to-date spend is $0.42 against the $75 cap.

## Priority (owner's answers, 2026-11-19)

The owner answered the open questions:
- Weapons and ammunition always matter.
- Small drug amounts do not, whether they are in kg or lb.
- Port contraband counts as a seizure, but must not weigh the same as weapons, human smuggling or large drug loads.

Seizures now carry a code-set `low_priority` flag (`docs/framework/seizure-priority.md`, migration 0012):
- fentanyl under 1 kg, other drugs under 10 kg, doses and contraband goods are low priority;
- weapons, ammunition, explosives, precursors and cash are never low priority.

The feed hides documents whose only records are low-priority seizures, and the evaluation reports those records separately. Once the existing records are reprioritized, 88, 91, 92 and 97 are low priority, and their extracted values can be labeled correct.
