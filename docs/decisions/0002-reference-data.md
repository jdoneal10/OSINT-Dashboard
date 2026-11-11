# ADR 0002 — Phase 1 reference data: sources and USBP sector representation

- **Status:** Accepted
- **Date:** 2026-11-11
- **Scope:** `data/reference/`, `scripts/build_reference.py`, `nodes` schema

## Context

Phase 0 needs committed, cited reference data for the Phase 1 area of interest (AOI): the six Mexican and four U.S. border states, the Southwest land ports of entry (POEs), the nine U.S. Border Patrol (USBP) sectors, and a seed list of TCO actors. CLAUDE.md requires a public source citation on every entry (hard rule 2), organizations only (hard rule 3), and no data whose purpose is locating U.S. law-enforcement positions or capabilities (hard rule 4).

## Decisions

### AOI state boundaries: Natural Earth 1:10m admin-1 (public domain)

All ten states come from one source, so the border between the two countries lines up. Geometry is simplified to about 500 m and rounded to 4 decimals (84 KB committed). That is fine for reference outlines but not for point-in-polygon tests near boundaries; Phase 2 admin2 work should use INEGI / Census boundaries. The plan had named Census for the U.S. states; one source was chosen instead to avoid boundary mismatches along the border.

### Ports of entry: BTS Border Crossing Entry Data (keg4-3bc2)

There is one point per BTS port code on the U.S.–Mexico border (28 ports), using the coordinates as BTS publishes them. These are public crossing points, the same units CBP uses to report port-of-entry statistics. Known data caveats:

- BTS groups some crossings under one port code (for example, several bridges under Hidalgo).
- Calexico and Calexico East share the same published coordinates.

### USBP sectors: names and codes only, no geometry

No current public GIS dataset of sector boundaries was found. HIFLD Open was retired in 2025, and the mirrors checked (Data Rescue Project, NASA NCCS) do not include a sector layer.

The nine Southwest Border sectors are therefore stored as `usbp_sector` nodes with **null geometry**, each citing its CBP public sector page. This is enough for Phase 1, which joins CBP statistics by sector name.

Rejected alternative: approximate sector polygons assembled from county lists. The boundaries would be inferred, and some would likely be wrong.

`nodes.point` was made nullable to allow this.

**Never stored:** Border Patrol station, checkpoint or facility locations. Sectors are statistical aggregation units only (hard rule 4).

### Actors: State Department FTO designations (90 FR 10030)

The seed is the six Mexico-based organizations designated on 2025-02-20 (Public Notice 12672). Names and aliases are as printed in the notice, without accents, which is how the fetched notice text renders them. Matching is accent- and case-insensitive.

One alias, "Osiel Cardenas-Guillen Organization", contains a person's name. It is kept because it is the organization alias exactly as printed in the designation.

Later designations were not checked: state.gov refused automated fetches. They will be added only after checking against the Federal Register.

## Consequences

- `scripts/build_reference.py` regenerates the GeoJSON from snapshots in `data/raw/reference/<date>/`, which are not committed.
- The map shows the AOI and POEs. Sectors appear as a list, not on the map, until a public boundary source exists. Any future sector geometry needs a new ADR that names its source.
