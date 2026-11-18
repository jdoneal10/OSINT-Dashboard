"""Critical-infrastructure keep rule for the local relevance filter (ADR 0012, owner decision
2026-11-17; narrowed the same day).

Owner judgment, not sourced fact: incidents involving critical infrastructure can have TCO
ties that are not visible at first (fuel theft, extortion of utilities, attacks on telecom),
so such a document is kept for extraction even when the local model scores it below the
threshold. The model's own score is still stored, so filter evaluation is not affected.
Deterministic and auditable: the matched terms are what decided it.

A document is kept when it either
- names an inherently criminal infrastructure activity (``ALWAYS``: fuel theft, illegal
  pipeline taps, cable or water theft), or
- names an infrastructure asset (``SECTORS``) **and** a criminal or deliberate-harm signal
  (``SIGNALS``: theft, sabotage, attack, armed men, explosives, extortion, cartel, hacking...).

So routine incidents (water-main leaks, a truck hitting a utility pole, planned outages,
workplace accidents) no longer qualify on their own; the local model still judges them.

Sectors: energy, water, communications, transport hubs. Highways are left out on purpose
(most highway alerts are protests and traffic). Change the lists here and bump
``RULE_VERSION``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

RULE_VERSION = "infra-v2"

SECTORS: dict[str, tuple[str, ...]] = {
    "energy": (
        r"pemex",
        r"cfe",
        r"comisi[oó]n federal de electricidad",
        r"pipelines?",
        r"oleoductos?",
        r"gasoductos?",
        r"poliductos?",
        r"ductos?",
        r"refiner(?:y|ies)",
        r"refiner[ií]as?",
        r"power (?:outages?|plants?|stations?|lines?|grid|cuts?|substations?)",
        r"electric(?:al|ity) (?:substations?|grid|infrastructure|supply|outages?|service)",
        r"substations?",
        r"subestaci[oó]n(?:es)?(?: el[eé]ctricas?)?",
        r"transmission (?:towers?|lines?)",
        r"torres? de (?:alta tensi[oó]n|transmisi[oó]n)",
        r"blackouts?",
        r"apag[oó]n(?:es)?",
        r"sin (?:luz|energ[ií]a el[eé]ctrica)",
        r"gas stations?",
        r"gasoliner(?:a|as|o|os)",
        r"fuel (?:stations?|tankers?|trucks?|depots?|terminals?)",
        r"pipas? de (?:gas|combustible)",
        r"gaseras?",
        r"gas pipelines?",
    ),
    "water": (
        r"water (?:supply|service|outages?|shortages?|mains?|pipes?|pipelines?|leaks?|"
        r"treatment|plants?|wells?|tanks?|infrastructure|system|utility)",
        r"wastewater",
        r"aqueducts?",
        r"acueductos?",
        r"agua potable",
        r"planta (?:potabilizadora|de tratamiento)",
        r"pozos? de agua",
        r"desabasto de agua",
        r"fuga de agua",
        r"dams?",
        r"presas?",
        r"reservoirs?",
        r"conagua",
    ),
    "communications": (
        r"telecom\w*",
        r"telecomunicaci[oó]n(?:es)?",
        r"fib(?:er|re)[- ]optic\w*",
        r"fibra [oó]ptica",
        r"cell(?:ular)? (?:towers?|service|network|signal|sites?)",
        r"(?:phone|telephone|mobile|radio) (?:towers?|service|lines?|network)",
        r"antennas?",
        r"antenas?",
        r"internet (?:service|outages?|connectivity|disruptions?|cables?)",
        r"telcel",
        r"telmex",
    ),
    "transport": (
        r"seaports?",
        r"ports? of entry",
        r"puertos? mar[ií]timos?",
        r"recintos? portuarios?",
        r"terminal(?:es)? portuarias?",
        r"container terminals?",
        r"airports?",
        r"aeropuertos?",
        r"railways?",
        r"railroads?",
        r"rail lines?",
        r"freight trains?",
        r"trenes? de carga",
        r"ferrocarril\w*",
        r"v[ií]as del tren",
        r"bridges?",
        r"puentes? (?:vehicular(?:es)?|ferroviarios?|internacional(?:es)?)",
    ),
}

# Inherently criminal infrastructure activity: kept with no further signal.
ALWAYS: tuple[str, ...] = (
    r"huachicol\w*",
    r"tomas? clandestinas?",
    r"(?:illegal|clandestine) (?:taps?|tapping)",
    r"fuel theft",
    r"(?:cable|copper|wire|water|electricity|power) theft",
    r"robo de (?:combustible|hidrocarburos?|gas|cables?|cobre|agua|energ[ií]a|electricidad)",
)

# Criminal or deliberate-harm signals that make an infrastructure mention worth keeping.
SIGNALS: tuple[str, ...] = (
    r"theft",
    r"thie(?:f|ves)",
    r"stol(?:e|en)",
    r"steal\w*",
    r"robb(?:ery|eries|ed|ers?)",
    r"rob[oó]",
    r"robaron",
    r"asalt\w*",
    r"sabotage",
    r"sabotaje",
    r"vandal\w*",
    r"attack\w*",
    r"ataques?",
    r"atac\w+",
    r"armed (?:men|group|groups|individuals|subjects|attackers)",
    r"(?:hombres|sujetos|civiles) armados",
    r"gunmen",
    r"gunfire",
    r"shoot(?:ing|out)s?",
    r"balacera\w*",
    r"disparos",
    r"explosives?",
    r"explosivos?",
    r"artefactos? explosivos?",
    r"arson",
    r"set (?:on )?fire",
    r"prendieron fuego",
    r"extort\w*",
    r"extorsi[oó]n\w*",
    r"cobro de piso",
    r"cartels?",
    r"c[aá]rtel(?:es)?",
    r"criminal (?:group|groups|cell|cells|organization|organizations)",
    r"organized crime",
    r"(?:crimen|delincuencia) organizad[ao]",
    r"hack\w*",
    r"breach\w*",
    r"ransomware",
    r"data leaks?",
    r"drones?",
    r"kidnap\w*",
    r"secuestr\w*",
    r"threat\w*",
    r"amenaza\w*",
)


def _compile(terms: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(terms) + r")\b", re.IGNORECASE)


_SECTOR_PATTERNS = {sector: _compile(terms) for sector, terms in SECTORS.items()}
_ALWAYS = _compile(ALWAYS)
_SIGNALS = _compile(SIGNALS)


def _found(pattern: re.Pattern[str], text: str) -> list[str]:
    return sorted({m.group(0).lower() for m in pattern.finditer(text)})


@dataclass(frozen=True)
class InfraMatch:
    always: list[str]  # inherently criminal terms
    sectors: dict[str, list[str]]  # sector -> asset terms
    signals: list[str]  # criminal or deliberate-harm terms

    @property
    def keep(self) -> bool:
        return bool(self.always) or (bool(self.sectors) and bool(self.signals))


def infrastructure_match(text: str) -> InfraMatch:
    sectors = {}
    for sector, pattern in _SECTOR_PATTERNS.items():
        if found := _found(pattern, text):
            sectors[sector] = found
    return InfraMatch(_found(_ALWAYS, text), sectors, _found(_SIGNALS, text))


def keep_for_infrastructure(text: str) -> bool:
    """True when the owner's critical-infrastructure rule keeps this text."""
    return infrastructure_match(text).keep
