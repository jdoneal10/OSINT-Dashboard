# ADR 0012: Dataminr First Alert for social-media and Telegram reporting

- **Status:** Accepted (2026-11-17)
- **Date:** 2026-11-16, revised 2026-11-17
- **Decision owner:** project owner
- **Relates to:** ADR 0008 (hard rules, outbound allowlist, paid data), ADR 0010 Amendment 1 (Telegram agreement), CLAUDE.md hard rules 1, 3, 4 and 5

## Context
ADR 0010 left social media and Telegram without a collection method; the owner declined ScrapeAtlas as a paid scraper. The owner holds a **personal First Alert licence** from Dataminr (confirmed 2026-11-16; not through an employer or agency).

The first draft of this ADR (2026-11-16) planned API access. On 2026-11-17 the owner reported that:
- **Dataminr gave written permission** to use all First Alert data in this dashboard, including **processing with Claude**, and alerts **may be kept indefinitely**.
- **The API is not available** for a personal tool. First Alert instead emails **interval digests** (about 150 alerts a day; see the schedule change below) to the owner's **personal Gmail**.

A sample of 13 digests (2026-11-16 14:00 to 2026-11-17 18:00 HST, 193 alerts) was read locally. Each alert has a priority (Alert, Urgent, or "Update"), a time in HST, a geocoded place (often to the street), a one-line English caption ending in the source type ("Local News Outlet via Facebook", "Blog via Public Telegram Board"), often the original post and Dataminr's translation, a First Alert link carrying the alert ID, and usually a link to the original post. Linked platforms: X 50, Facebook 38, Citizen 8, Mexican outlets, two public Telegram boards. Most alerts are local incidents and protests; few are clearly TCO-related.

## Terms
- **Owner's written permission from Dataminr (2026-11-17)** governs this use: all First Alert data, Claude processing, indefinite retention. The API licence terms reviewed on 2026-11-16 (30/180-day retention, deleted-tweet certification) applied to API access and no longer govern, since no API is used.
- **First Alert third-party notice** (`/legal/firstalert-tos`) still applies to content inside the alerts: X content may not be used "for surveillance purposes", including alerting on or monitoring protests and rallies, or for profiling by protected category.
- **Telegram-sourced alerts** also fall under the owner's Telegram agreement (ADR 0010, Amendment 1).

## Decision
1. **Collection (owner side).** The owner runs a Gmail connector on the personal account. Twice a day, at 00:45 and 12:45 HST, it saves each digest's body, word for word, as a `.txt` file in `data/raw/dataminr/inbox/` (gitignored). The dashboard never signs in to Gmail, stores no mail credential, and makes no outbound call for this source, so the outbound allowlist is unchanged.
2. **Ingest (dashboard side).** A worker job (`dataminr`, every 30 minutes) and `make ingest SOURCE=dataminr`:
   - parse each inbox file into alerts; the stable key is Dataminr's alert ID;
   - copy the file to `data/raw/dataminr/<date>/` and remove it from the inbox only after its alerts are committed; a re-delivered file is recognized by its hash and is not ingested twice;
   - store each alert as a `documents` row: caption, place, source type, the original post (marked as an excerpt; Dataminr truncates it) and Dataminr's translation, time converted to UTC, link to the original post;
   - never store the First Alert redirect links (they carry an account key) or fetch alert images;
   - raise a `feed_gap` alert when a digest window is missing between received digests, and a `feed_stalled` alert when no new window has ended for 15 hours (one missed delivery).
3. **X content and sensitive events.** X-sourced alerts about protests, rallies, marches, strikes or sit-ins are dropped at ingest (the X term above; the project tracks TCO activity, not civil unrest). Blockades are **not** dropped by this rule, because cartel blockades (narcobloqueos) are threat activity. No profiling of people by protected category, ever.
4. **Relevance, with the owner's critical-infrastructure rule.** Alerts go through the local relevance filter like every document. **Owner decision (2026-11-17):** criminal or deliberate harm to critical infrastructure is kept even when the model scores it low, because TCO ties to infrastructure incidents can go unseen at first (fuel theft, extortion of utilities, attacks on telecom). The rule is deterministic keyword matching (`app/enrich/infrastructure.py`), applies to **all sources**, and records itself in `relevance_model` (`…+infra-v2`). A document is kept when it either:
   - names an inherently criminal activity: fuel theft, illegal pipeline taps (huachicol, tomas clandestinas), cable, copper, water or electricity theft; or
   - names an infrastructure asset **and** a criminal or deliberate-harm signal (theft, robbery, sabotage, vandalism, attack, armed men, gunfire, explosives, arson, extortion, cartel or organized crime, hacking or data breach, drones, kidnapping, threats).

   Assets: **energy** (Pemex, CFE, pipelines, refineries, power plants, substations, transmission lines, fuel stations and tankers), **water** (supply, mains, treatment plants, aqueducts, wells, dams), **communications** (telecom networks, towers, antennas, fiber-optic cable, internet and mobile service), **transport hubs** (seaports, rail, airports, bridges). Highways are not on the list (most highway alerts are protests and traffic).

   The first version (infra-v1, same day) kept any infrastructure mention and matched 35 of the first 176 alerts, mostly routine (water-main leaks, trucks hitting utility poles, planned outages). The owner narrowed it to the rule above, which keeps 3 of them (a Telmex equipment theft, a Telmex data breach, a robbery at a Pemex station). Routine incidents are still scored by the local model. The model's own score is always stored, so filter evaluation is unaffected.
5. **Hard rules.**
   - **Rule 1:** personal licence and personal Gmail only. If access moves to an employer or agency account, the source stops.
   - **Rule 3:** victims, bystanders and private individuals named in alerts never become person records (the extraction schema already enforces this).
   - **Rule 4:** security-force positions, patrols or operations are not recorded; TCO action against security forces is kept as threat activity (extraction rules apply).
6. **Analytic grade.** Source reliability **D**: an aggregator of mostly unverified social-media posts. A single Dataminr alert stays at credibility 6 until press or official reporting corroborates it. All Dataminr alerts share one source, so two alerts never corroborate each other. Dataminr's "Urgent" label is not a credibility rating. An alert that links an outlet's article already ingested from that outlet is a duplicate and counts once.
7. **Cost.** Covered by the owner's personal licence; nothing is paid by the project. Claude spend falls under the existing monthly cap.

## Schedule change (2026-11-18)
First Alert digests moved from 2-hour windows to **twice daily**, covering 00:00–12:00 and 12:00–24:00 HST. The owner's connector now runs at 00:45 and 12:45 HST. Parsing and gap detection already handle windows of any length. The stall threshold went from 12 to 15 hours: with 12-hour windows, a 12-hour threshold would fire every night just before the 00:45 delivery.

## Consequences
- The project gains near-real-time social-media and public-Telegram coverage, the gap ADR 0010 left open, without an API key or an outbound connection.
- Coverage depends on the owner's connector running; the gap alert makes a missed digest visible.
- Dropping X-sourced protest alerts loses some context the mission does not need.
- The critical-infrastructure rule adds only a few documents a day to Haiku; the cost is negligible within the budget cap.
- ScrapeAtlas gap-filling for Telegram channels Dataminr misses remains a later, separate decision (it would need its own paid-data ADR).
