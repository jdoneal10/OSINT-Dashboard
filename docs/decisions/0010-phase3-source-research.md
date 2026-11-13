# ADR 0010: Phase 3 sources — what to add, what to drop

- **Status:** Proposed (awaiting owner approval)
- **Date:** 2026-11-13 (revised the same day after owner review)
- **Decision owner:** project owner
- **Relates to:** ADR 0008 §2 and §6 (outbound calls, sources); ADR 0009 §3 (sources to research); ADR 0004 (news pipeline)

## Context
ADR 0009 named four source groups to research for unmanned systems (UxS) and electricity theft. Each was checked on 2026-11-13 against its robots.txt and published terms. The owner then:
- supplied three Pixtoday.net exports and reported explicit permission to use them;
- pointed to a Telegram update of 2026-11-09;
- asked for a free search option that reaches blogs and forums;
- asked for as many outlets as possible.

Nothing has been ingested.

## Findings

### Official bulletins
| Source | Finding |
|---|---|
| gob.mx press listings: Guardia Nacional, Defensa (SEDENA), SSPC | **Usable.** robots.txt has no `*` group. The [gob.mx terms](https://www.gob.mx/terminos) allow personal, non-commercial viewing and downloading, with no public display, redistribution or transfer, which is the same handling as the SEMAR and FGR feeds. FGR's listing returned HTTP 500 on 2026-11-13. |
| CFE bulletins (`app.cfe.mx`) | **Not automated.** The bulletin app sits behind bot protection. The owner accepts GDELT and press coverage of CFE cases instead. |

### Pixtoday.net
`pixtoday.net` disallows every agent in robots.txt, so nothing is fetched automatically. The owner exports files while signed in and imports them, as for SESNSP. The owner reports explicit permission to use this data, including processing with Claude (confirmed 2026-11-13). The three files of 2026-11-13 were profiled locally. A case-sensitive scan for control markings (FOUO, CUI, LES, NOFORN, classification words) found none.

| File | Content | Relevance | Handling |
|---|---|---|---|
| `PiX_MEX_ActiveCartels_Events_<date>.csv` | 295 geocoded events, 2026-11-01 to 11-12. PiX-written summaries of X posts, each with the post URL and cartel attribution | **High for UxS:** 7 drone events in 12 days, including a drone-dropped explosive attack, a CJNG gunman with an anti-drone gun, and 7 seized drone-launched explosive devices. **Electricity theft:** 1 relevant event (130 crypto-mining rigs seized in Culiacán). Also high for violence and territory | Low Admiralty grade: social-media claims compiled by an aggregator, single source unless corroborated. Rule 4: the 16 "Government / Military Operations" rows are dropped, and from "Security Operations" rows only the TCO action is kept. Victims and bystanders named in summaries never become person records |
| `dataset_693_export_<date>.csv` | 167 Mexican criminal-organization profiles: aliases, parent organization, factions, allies, enemies, areas, equipment and `UAV_Use`. Each row has up to 10 cited sources (Infobae, InSight Crime, Milenio and others) | **High** as cited reference data. It extends `actor_aliases.yaml` and alliances, and `UAV_Use` gives 11 cited baselines for UxS PIR 1 | Reference data under rule 2, with each row's citations carried over. Organizations only, so no person issues |
| `PiX_MEX_PrecursorEntities_<date>.xlsx` | 700 organizations (482 Mexico, 151 China, 499 OFAC-designated), 966 locations, 177 events and 1,012 fentanyl supply-chain rows, 2015–2026 | **Phase 4** (precursors). Not used in Phase 3 | Rule 3 applies when imported: phone numbers and email addresses are dropped, affiliated individuals become person records only with the safeguards, U.S. entries are flagged `us_person`, and business addresses are kept only for businesses reported as fronts or designated. Working sheets (form responses with contributor initials, link lists, cover sheets) are skipped |

### Telegram
**Still excluded.** The 2026-11-09 change is Bot API 10.4: HTML widgets, ephemeral replies and gifts. Its "queries" are widget queries, not channel reads. The current terms go the other way:
- [Bot developer terms](https://telegram.org/tos/bot-developers) §4.3 lists "scraping public group or channel contents" among always-prohibited uses.
- The [content-licensing terms](https://telegram.org/tos/content-licensing) still prohibit using platform data for AI. Their only bot exception covers data needed to operate the bot.
- Technically, bots receive posts only from channels they are members of.

Cartel material first posted to Telegram still arrives through press reporting and through PiX's compilations of reposts on X.

### Search for blogs, forums and non-news sites
| Option | Cost | Terms | Finding |
|---|---|---|---|
| [Marginalia Search API](https://about.marginalia-search.com/article/api/) | Free non-commercial key, requested by email; no card | Data under CC BY-NC-SA 4.0; no storage or AI restriction found | **Recommended.** An independent index with a strong lean to blogs and small sites. Its quota and Spanish coverage are unpublished, so a trial query set is run first |
| [Mojeek API](https://www.mojeek.com/about/legal/api-terms.html) | ~£3 per 1,000 queries (about £4.50 a month at our volume); card required | §6.1 explicitly allows AI applications. Storage only on the Business plan | **Best terms, but paid.** Revisit under a paid-data ADR |
| Exa | Free tier, no card | Terms clause (j) bars automated queries "to monitor, extract, copy or collect" data, and grant Exa a perpetual licence to our queries | **Excluded.** Scheduled monitoring is what we would do |
| Tavily | Free tier, no card | Limited to "internal business purposes"; lists surveillance as a prohibited use | **Excluded.** Poor fit for personal use |
| Brave | Paid for storage | ToS §3(b)(i): no storing results | **Deferred.** Paid data |
| Common Crawl | Free | Open; AI use is an indemnity trigger | **Not now.** URL index only, no keyword search |
| Reddit, Stack Exchange | — | Terms could not be read | **Unverified.** Needs the owner to read them before any ADR |
| SearXNG, Google CSE, Bing, DuckDuckGo | — | Scrapes engines, closed, retired, or no API | **Not viable** |

Blogs with their own feeds (Borderland Beat, Small Wars Journal) are registered directly instead of found through search.

### Outlets
robots.txt was checked on 2026-11-13 for our client (`cartel-osint/0.1`) and for Claude agents. Each outlet's terms are read and recorded in `feeds.yaml` when its feed is added, as in Phase 2.

| Group | Pass robots.txt |
|---|---|
| Mexican national and security press | El Financiero, Infobae, La Jornada, OEM (El Sol de México and regional titles), El Sol de México, Aristegui Noticias, Latinus, La Silla Rota, Eje Central, Emeequis, Expansión, El Economista, Contramuro |
| Regional press | **Sinaloa:** Noroeste, Línea Directa. **Sonora:** El Imparcial, Expreso. **Michoacán** (drone hotspot): Quadratín, MiMorelia (`ai-input=yes`), Changoonga |
| Blogs and analysis | Borderland Beat, Small Wars Journal |
| Energy | Energía Estratégica, Energía Hoy, pv magazine México |
| Drone and defense | The War Zone (`ai-input=yes`), DroneDJ, DroneLife, sUAS News, Unmanned Airspace, Infodefensa, Defensa.com, Zona Militar, Defense News, Breaking Defense, Army Recognition |
| U.S. border | Texas Tribune, KGNS (Laredo), KTSM (El Paso) |

**Excluded or pending:**
- **Disallow our client:** El Diario de Chihuahua, Radio Fórmula, Reporte Índigo.
- **Block Claude agents:** El País, Energía a Debate.
- **robots.txt unreadable (403, 504 or connection error):** SinEmbargo, Narco Chronicles, Crisis Group, Oil & Gas Magazine, Animal Político. These are rechecked once and dropped if still unreadable.

## Decision
1. **Official bulletins.** Register the Guardia Nacional, Defensa and SSPC listings with SEMAR and FGR handling. CFE cases come through GDELT and press.
2. **Pixtoday.net by owner export.** Build file importers for the event export (`make ingest SOURCE=pixtoday FILE=path`) and the organization dataset (reference data). The precursor workbook waits for Phase 4.
   - Raw files go to `data/raw/pixtoday/<date>/` and are never committed.
   - Every record cites PiX and the underlying source URL.
   - The owner's permission is recorded here. The owner confirmed on 2026-11-13 that it covers processing with Claude, so PiX records go through the normal LLM stages.
3. **Telegram.** Not collected.
4. **Search.**
   - The owner requests a free non-commercial Marginalia key and stores it in Keychain.
   - The framework taxonomy runs against Marginalia (blogs and small sites) and GDELT (news).
   - Mojeek is the first candidate if a paid-data ADR is ever written.
5. **Outlets.** Add the robots-cleared outlets above in batches, reading and recording each one's terms first. Michoacán, Sinaloa and drone-press feeds go first, because they carry the most UxS reporting.
6. **Outbound allowlist.** The first new host comes with the config allowlist that ADR 0008 §2 requires.

## Consequences
- Phase 3 gains a high-yield UxS stream from PiX. It is social-media-derived, so its Admiralty grades stay low until press or official sources corroborate it.
- About 40 new feeds raise volume, so the local relevance filter carries more load and Haiku spend rises. Each batch is checked against the $75 budget cap before the next is added.
- No Telegram and no paid search. Coverage of the earliest single-source claims depends on PiX and the press.
- The `UAV_Use` and alliance fields bring cited reference data in faster than news extraction would.
