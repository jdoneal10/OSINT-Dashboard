# ADR 0013: Person records — schema, extraction and safeguards

- **Status:** Accepted (2026-11-20)
- **Date:** 2026-11-20
- **Decision owner:** project owner
- **Implements:** ADR 0008 §4 (hard rule 3); PLAN Phase 3
- **Relates to:** ADR 0005 (superseded), ADR 0009 (PIRs on facilitators, operators and suppliers)

## Context
ADR 0008 allows person records for individuals an open source links to TCO activity, with safeguards: every claim cited, dated and graded; excluded categories never recorded; no contact or personal-life details; U.S. persons hidden by default; owner dispute and delete. ADR 0005's ban on person tables no longer applies. This ADR records how the build meets those conditions.

## Decision
1. **A person is a set of cited claims.** `persons` holds only a display name, a matching key, the `us_person` flag and the owner's dispute state. Everything else is a claim row in one of three tables:
   - `person_attributes`: role, alias, nationality, status, title;
   - `person_organizations`: a link to an actor, with a role;
   - `person_events`: a link to an event, with a role.

   Every claim row carries its source, the document (or designation) it came from, the report date, the source's reliability, a credibility grade and a short evidence quote. The database refuses a claim with no document or designation. A person left with no claim is deleted, so no uncited person exists. Views show each claim "as reported".
2. **No column for forbidden data.** The schema has no field for addresses, phone numbers, emails, ID or account numbers, or health or family details. Values that look like contact or ID details (an @, a URL, a long digit run, CURP/RFC/INE/passport) are dropped before storage.
3. **Extraction (`extract-v8`).** Haiku lists persons with a role from a fixed set:
   - roles: leader, member, facilitator, operator or technician, supplier, front-business owner, financier, complicit official, associate;
   - excluded, and described by role instead: victims, bystanders, witnesses, uninvolved relatives, journalists, minors, and officials not reported as complicit;
   - storage drops anyone the model marks as a reported minor.

   A person is linked to events from the same output by index. Re-extracting a document replaces all of its person claims.
4. **U.S. persons.** A claim that reports U.S. citizenship, residence or presence in the United States sets `us_person`. The API leaves those records out of lists, search and detail unless `include_us_persons=true` is passed. This supports the owner's EO 12333 boundary; it is a safeguard, not a determination.
5. **Matching is conservative.** Reports join an existing person only on an exact normalized full name of two or more words with no placeholder (such as Mexico's "N" surname). Thinner names start a new record. A wrong merge would attach one person's claims to another; a missed merge only splits a record, which the owner can see and later fix.
6. **Owner control.** `PUT /persons/{id}/dispute` marks a record disputed with a note, or clears it. `DELETE /persons/{id}` removes the record and all of its claims and links. Disputed records stay visible and labeled, and they can be filtered out.
7. **Credibility.** A single report gets the Admiralty credibility that the source's reliability implies (A→2, B→3, C→4, otherwise 6). Corroboration across sources is shown by the number of independent sources on the record. Re-grading by corroboration is left for later.

## Not in this step
- **SDN individuals.** About 700 OFAC SDN individuals are already stored only as names inside designation records. Turning them into person records needs their published citizenship and address country, which the SDN ingester does not keep yet, so U.S. persons can be flagged. That waits for a follow-up step.
- **The person view and labeling fields** (Phase 3 step 5). The exit criterion "zero labeled person-safeguard violations" is measured there.

## Consequences
- IR 8 and 9 questions about facilitators, operators and suppliers become answerable with citations.
- Person data comes only from source text Haiku has read. Its quality depends on the prompt and is measured by the owner's labels.
- Conservative matching will split some people across records until a reviewed merge tool exists.

## Amendment 1 (2026-11-22): enforced safeguards and reviewed merges

- **Status:** the owner approved the scope on 2026-11-22 ("Fix, then merge"); wording to be reviewed before commit.
- **Why:** in the first stored records, up to 87 of 122 looked like duplicates of about 10 people. The review also found surnames the cited articles do not contain, family details in titles and quotes, a third party named in a quote, names with "de la" that never matched, nicknames that did, article counts shown as source counts, and owner decisions that re-extraction could clear.

### Safeguards enforced at storage (`app/enrich/person_guard.py`)
- **Names.** A name or alias is stored only if the title or text the model was shown contains it. Otherwise the text's own "given name + N" is used, then an alias the text has. Failing both, the person is not stored.
- **Family details.** Kinship is cut from titles. A quote carrying it is withheld; the claim stays cited to its document.
- **Third parties.** A quote naming someone by a non-criminal role (official, journalist, victim and similar) who is not a listed person is withheld.
- **Limit.** These are word lists and patterns. They do not catch a bare third-party name with no role word beside it, so the owner's labels remain the measure. They cover person records only, not event descriptions or document summaries.

### Matching (replaces decision 5's rule)
- **Automatic.** A report joins a record only on an exact normalized name of at least three name words, not counting particles ("de la"), that has no "N" and does not start as a nickname ("El ..."). Two-word names no longer join, because they can be two given names or a nickname.
- **Re-extraction.** A document reuses its own records, so ids, disputes, merges and labels survive.

### Reviewed merges (`person_merges`, `person_distinctions`; migration 0016)
- **Only the owner merges.** `/persons/review` suggests groups with reasons. A masked name with no shared alias is never pre-ticked, nor are two records named separately in one article.
- **Nothing moves.** A merge is a link. Every claim, citation and label stays on its record, every claim shows the name its source published, and the heading says which source published the name shown.
- **Reversible.** Each link can be undone. "Not the same person" is remembered, blocks merging and suggestion, and can be undone.
- **U.S. persons.** An identity is hidden by default if any of its records is flagged, and so is any suggestion containing one.
- **Dispute and delete** act on the whole identity.

### Source count (corrects decision 7)
The list shows distinct outlets and, separately, articles. Outlets reprint one another, so neither number is a count of independent confirmations.

### Stored records
`python -m app.enrich.person_repair` (report only; `--apply` writes) applies these rules to existing records. It is idempotent, makes no model call, never deletes, merges or splits a person, and never changes a label. Labels saved before the repair judge the record as it then read.

## Amendment 2 (2026-11-22): family details in summaries and event text

- **Status:** the owner approved the scope on 2026-11-22 ("Yes, fix those"); wording to be reviewed before commit.
- **Why:** amendment 1 covered person records only. Model-written summaries, event descriptions and event quotes still tied people to relatives.
- **Definition.** A family detail is kinship tied to an identifiable person: named, aliased, or given as "the leader" or "the target". Relatives described only by role (mothers of the disappeared, families stranded, a man walking with his wife) are ordinary reporting and stay.
- **At storage (`app/enrich/text_guard.py`).** Kinship is cut only directly before a listed person's name or as an aside after one. Otherwise the sentence is withheld, because "the brother of X was sentenced" must never become "X was sentenced". Quotes are withheld whole. A person name the text lacks is corrected in free text the same way as in the person record, when that person is listed.
- **Stored text (one-time, reviewed replacements).** No labels changed; changed events carry `attributes.corrected`.
  - Summaries: documents 59, 90, 108, 126, 130, 424, 459, 695, 1174, 1184, 1345, 1566, 1922, 1945, 2007, 2060, 2079, 2090, 2123.
  - Events: 267824, 267826, 267828, 267902, 268194, 268204, 268273, 268359, and 268378 (a surname its article does not contain).
  - Quotes withheld: events 267902, 268273.
- **Unchanged:** source titles, article text and URLs, which are the sources' own words; ACLED notes; raw model output in quarantine, which the API does not serve.
- **Limit.** Patterns reduce the risk and do not prove absence.
