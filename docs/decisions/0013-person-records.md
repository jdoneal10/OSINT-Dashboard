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
