# Owner framework: seizure priority

> UNCLASSIFIED — OPEN-SOURCE INFORMATION ONLY
>
> **Owner judgment, not sourced fact (CLAUDE.md rule 2).** This framework records the owner's answers of 2026-11-19 on which seizures matter. It sets a priority flag. It never changes what a source reported, and it does not judge whether an extraction is correct.

## Why

Weapons and ammunition increase lethality and border violence, so they always matter. Small drug amounts and small contraband goods add noise. They should not carry the same weight as weapons, human smuggling or large drug loads. Port seizures of contraband still count as seizures.

## Rule (applied per record, by that record's own item and amount)

| Item | Priority |
|---|---|
| Firearms, ammunition, magazines, explosives | normal, always |
| Precursor chemicals, cash, anything else not listed below | normal |
| Fentanyl under 1 kg | **low** |
| Any other drug (including an unidentified drug) under 10 kg | **low** |
| Drugs counted in doses | **low** (retail amounts) |
| Contraband goods (`contraband <goods>`) | **low**, at any size |
| A drug with no measurable amount (no figure, packages only, "other" unit) | normal (it cannot be sized, and hiding it could hide a large load) |

- Each record is judged on its own item and amount. A drug record from an operation that also seized weapons is judged on the drug amount. The weapons record from that operation is normal priority.
- Pounds, grams and litres are converted to kg for the comparison only (1 lb = 0.4536 kg, 1 l ≈ 1 kg); the stored unit stays as the source wrote it. Pressed pills count as about 0.1 g each.
- Counterfeit-trademark goods with no smuggling or criminal-group link are not seizures at all (extract-v6, rule S1).

## Where it applies

- `seizures.low_priority` is set by code (`app.enrich.extract.seizure_low_priority`) when a record is stored. The model plays no part. To recompute existing records after a threshold change, run `python -m app.enrich.extract --reprioritize` (local, free).
- The news feed hides a document whose only records are low-priority seizures. The filter "Include low-priority seizures" brings them back. Document pages show a "low priority" badge on these records.
- The evaluation report counts labeled low-priority seizures separately. Label them on extraction accuracy alone.
