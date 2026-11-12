# Evaluations

Dated reports from `make eval` (`backend/app/enrich/evaluate.py`), one per run and prompt version:
`<date>-extraction-<prompt_version>.md`.

- **Input:** the project owner's hand labels from the in-app labeling page (`/labeling`).
- **What a report holds:** counts, rates, confidence intervals and record ids. It holds no article text, label notes or names.
- **Phase 2 exit criterion:** strict extraction precision of at least 85%, over at least 100 labeled documents.
- **Filter comparison:** `make eval MODELS=qwen3:4b,gemma3:4b` re-scores the labeled documents with each local Ollama model. Nothing is stored and nothing leaves the machine.
- **Prompt changes:** every change bumps `PROMPT_VERSION` in `app/enrich/extract.py`. Labels are tied to the version they judged, so each prompt is evaluated on its own labels.
