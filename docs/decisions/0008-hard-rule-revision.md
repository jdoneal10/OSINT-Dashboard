# ADR 0008: Revised hard rules for a personal open-source analytic aid

- **Status:** Accepted
- **Date:** 2026-11-13
- **Decision owner:** project owner
- **Amends:** CLAUDE.md hard rules 1–5 and 7, the "Do not" list, and the LLM pipeline rules
- **Supersedes:** ADR 0005 (naming reported criminal-organization leaders); PLAN.md decisions 1 and 5

## Context
The project began as a portfolio piece built only on publicly published information, and organizations were its unit of analysis. On 2026-11-13 the owner refocused it on two topics, unmanned systems (UxS) and electricity theft, and reviewed the hard rules against that work.

**Unpublished open-source material:** much of the useful information is open source but not published as a dataset. Examples are commercial imagery behind a free account and account-based aggregators.

**People, not hierarchies:** TCOs and the businesses around them do not have traditional hierarchies. They are loose, people-driven networks, so an organizations-only model misses most of the picture.

**What the tool is for:** a personal analytic aid that gives the owner a first look before their own analysis. It decides nothing about anyone.

## Decision
1. **Rule 1: open source, not only published.**
   - **Allowed:** unclassified information the owner can lawfully hold on a personal system. That covers published sources, account-based or licensed commercial data used within its terms, and unpublished material the owner collects lawfully.
   - **Excluded:**
     - classified information;
     - CUI, including FOUO and LES;
     - anything from a government system or obtained through official duties.

     Unclassified does not mean releasable to a personal system or a commercial API, so these exclusions stay absolute.
   - **Banner:** the UI banner becomes `UNCLASSIFIED — OPEN-SOURCE INFORMATION ONLY`.
   - **Imagery:** the owner's commercial imagery comes from a personal account, not a government contract. Its licence terms are recorded before ingest, including whether it may be processed with Claude.
2. **Outbound calls.** Allowed to destinations listed in `docs/data-sources.md`:
   - source pulls;
   - the Claude API;
   - services an ADR approves.

   A config allowlist that enforces the list arrives with the first new destination. Telemetry and analytics stay prohibited.
3. **Rule 2: the owner's framework.** The owner's analytic notes live in `docs/framework/`, labeled as owner judgment. They may shape prompts, priority intelligence requirements (PIRs) and scoring, but they are never stored or shown as sourced fact. Reference data still requires a citation for every entry.
4. **Rule 3: people linked to criminal activity.**
   - **Who:** person records, links and views are allowed for individuals an open source links to TCO activity:
     - members, leaders and facilitators;
     - operators, technicians and suppliers;
     - owners of front businesses;
     - people named in indictments, designations, sanctions or prosecutions.
   - **Safeguards:**
     - every attribute and link cites its source and date, carries that source's Admiralty grade, and is shown as reported;
     - victims, bystanders, witnesses, uninvolved relatives, journalists and minors are never person records, and officials are recorded only when a source reports them as complicit;
     - no contact or personal-life details;
     - U.S. persons are flagged `us_person` and excluded from person views and search by default;
     - the owner can mark records disputed or delete them.

   The U.S.-person filter supports the owner's stated intent to stay within EO 12333 limits. The owner is responsible for that boundary; the filter is a safeguard, not a determination.
5. **Rule 4: clarified, not relaxed.** TCO action against security forces is recorded as threat activity, meaning a mission or target category plus the location at the source's precision. Units, positions, checkpoints, patrols and counter-UAS capabilities are never recorded.
6. **Rule 5: sources.**
   - Social media, account-based sources, forums and paid data each need their own ADR that records the terms and how access works.
   - The owner signs in to account-based sources, and their credentials never enter the repo.
   - Agreed in principle, pending those ADRs:
     - public Telegram channels through the official API;
     - a sanctioned search API in place of search-engine scraping;
     - forums case by case.
   - Paid data may be revisited later.

## Consequences
- **Person model:** a person table, person-to-organization links and person views become possible. They are designed with the UxS and electricity-theft work. The extraction prompt then records people as the safeguards in §4 allow, and the labeling page measures violations.
- **Leaders in free text:** ADR 0005's free-text rule for leaders is absorbed into §4.
- **Higher error cost:** errors about named people matter more than errors about organizations. Every person attribute stays traceable to a source and graded, and the UI says "reported" rather than asserting.
- **PLAN.md changes:** the workspace classification line, purpose, audience and decisions log are updated to match.
