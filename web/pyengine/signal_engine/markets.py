"""Configurable target markets and location classification.

Location is decided ONLY from credible place evidence:
  * structured country codes from an official source (e.g. TED buyer-country, OCDS address), or
  * a country, region or city NAME in the text.
Currency symbols (£, €, AED) are never location evidence.

Markets (edit TARGET_MARKETS to change scope):
  UK      – United Kingdom incl. Crown Dependencies
  UAE     – United Arab Emirates
  Europe  – every European country, EU and non-EU (incl. Switzerland, Norway, Iceland, the
            Balkans, microstates, Ukraine, Moldova). Transcontinental countries are included
            but flagged; Russia and Belarus are included but flagged for sanctions review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# name -> (ISO2, ISO3, market, flags)
COUNTRIES: dict[str, tuple[str, str, str, tuple[str, ...]]] = {
    # UK + Crown Dependencies
    "United Kingdom": ("GB", "GBR", "UK", ()),
    "Jersey": ("JE", "JEY", "UK", ()), "Guernsey": ("GG", "GGY", "UK", ()), "Isle of Man": ("IM", "IMN", "UK", ()),
    # UAE
    "United Arab Emirates": ("AE", "ARE", "UAE", ()),
    # EU-27
    "Austria": ("AT", "AUT", "Europe", ()), "Belgium": ("BE", "BEL", "Europe", ()), "Bulgaria": ("BG", "BGR", "Europe", ()),
    "Croatia": ("HR", "HRV", "Europe", ()), "Cyprus": ("CY", "CYP", "Europe", ()), "Czechia": ("CZ", "CZE", "Europe", ()),
    "Denmark": ("DK", "DNK", "Europe", ()), "Estonia": ("EE", "EST", "Europe", ()), "Finland": ("FI", "FIN", "Europe", ()),
    "France": ("FR", "FRA", "Europe", ()), "Germany": ("DE", "DEU", "Europe", ()), "Greece": ("GR", "GRC", "Europe", ()),
    "Hungary": ("HU", "HUN", "Europe", ()), "Ireland": ("IE", "IRL", "Europe", ()), "Italy": ("IT", "ITA", "Europe", ()),
    "Latvia": ("LV", "LVA", "Europe", ()), "Lithuania": ("LT", "LTU", "Europe", ()), "Luxembourg": ("LU", "LUX", "Europe", ()),
    "Malta": ("MT", "MLT", "Europe", ()), "Netherlands": ("NL", "NLD", "Europe", ()), "Poland": ("PL", "POL", "Europe", ()),
    "Portugal": ("PT", "PRT", "Europe", ()), "Romania": ("RO", "ROU", "Europe", ()), "Slovakia": ("SK", "SVK", "Europe", ()),
    "Slovenia": ("SI", "SVN", "Europe", ()), "Spain": ("ES", "ESP", "Europe", ()), "Sweden": ("SE", "SWE", "Europe", ()),
    # Non-EU Europe
    "Switzerland": ("CH", "CHE", "Europe", ()), "Norway": ("NO", "NOR", "Europe", ()), "Iceland": ("IS", "ISL", "Europe", ()),
    "Liechtenstein": ("LI", "LIE", "Europe", ()), "Monaco": ("MC", "MCO", "Europe", ()), "Andorra": ("AD", "AND", "Europe", ()),
    "San Marino": ("SM", "SMR", "Europe", ()), "Vatican City": ("VA", "VAT", "Europe", ()),
    "Serbia": ("RS", "SRB", "Europe", ()), "Montenegro": ("ME", "MNE", "Europe", ()),
    "Bosnia and Herzegovina": ("BA", "BIH", "Europe", ()), "North Macedonia": ("MK", "MKD", "Europe", ()),
    "Albania": ("AL", "ALB", "Europe", ()), "Kosovo": ("XK", "XKX", "Europe", ()),
    "Ukraine": ("UA", "UKR", "Europe", ()), "Moldova": ("MD", "MDA", "Europe", ()),
    "Turkey": ("TR", "TUR", "Europe", ("transcontinental",)), "Georgia": ("GE", "GEO", "Europe", ("transcontinental",)),
    "Armenia": ("AM", "ARM", "Europe", ("transcontinental",)), "Azerbaijan": ("AZ", "AZE", "Europe", ("transcontinental",)),
    "Belarus": ("BY", "BLR", "Europe", ("sanctions_review",)), "Russia": ("RU", "RUS", "Europe", ("sanctions_review", "transcontinental")),
}

TARGET_MARKETS = ("UK", "UAE", "Europe")

# Extra names / spellings that map to a country (lower-case keys).
ALIASES = {
    "uk": "United Kingdom", "u.k.": "United Kingdom", "great britain": "United Kingdom", "britain": "United Kingdom",
    "england": "United Kingdom", "scotland": "United Kingdom", "wales": "United Kingdom", "northern ireland": "United Kingdom",
    "uae": "United Arab Emirates", "u.a.e.": "United Arab Emirates", "emirates": "United Arab Emirates",
    "czech republic": "Czechia", "the netherlands": "Netherlands", "holland": "Netherlands",
    "deutschland": "Germany", "españa": "Spain", "schweiz": "Switzerland", "suisse": "Switzerland", "svizzera": "Switzerland",
    "türkiye": "Turkey", "turkiye": "Turkey", "macedonia": "North Macedonia", "bosnia": "Bosnia and Herzegovina",
    "republic of ireland": "Ireland", "éire": "Ireland",
}

# Cities: proper-noun match only (case-sensitive) and ambiguous English words excluded
# on purpose (e.g. Nice, Reading, Bath, Split, Wells, Mobile).
CITIES = {
    "United Kingdom": ["London", "Manchester", "Birmingham", "Leeds", "Glasgow", "Edinburgh", "Bristol", "Liverpool",
                       "Sheffield", "Newcastle", "Cardiff", "Belfast", "Nottingham", "Leicester", "Brighton",
                       "Southampton", "Aberdeen", "Coventry", "Milton Keynes", "Kent", "Surrey", "Yorkshire"],
    "United Arab Emirates": ["Dubai", "Abu Dhabi", "Sharjah", "Ajman", "Ras Al Khaimah", "Fujairah", "Umm Al Quwain"],
    "France": ["Paris", "Lyon", "Marseille", "Toulouse", "Bordeaux", "Lille", "Nantes", "Strasbourg", "Montpellier"],
    "Germany": ["Berlin", "Munich", "München", "Hamburg", "Frankfurt", "Cologne", "Köln", "Stuttgart", "Düsseldorf", "Leipzig"],
    "Spain": ["Madrid", "Barcelona", "Valencia", "Seville", "Sevilla", "Bilbao", "Málaga", "Malaga"],
    "Italy": ["Rome", "Roma", "Milan", "Milano", "Turin", "Torino", "Naples", "Napoli", "Florence", "Bologna"],
    "Netherlands": ["Amsterdam", "Rotterdam", "The Hague", "Den Haag", "Utrecht", "Eindhoven"],
    "Belgium": ["Brussels", "Bruxelles", "Antwerp", "Antwerpen", "Ghent", "Gent", "Liège"],
    "Switzerland": ["Zurich", "Zürich", "Geneva", "Genève", "Basel", "Lausanne", "Bern", "Lugano", "Zug"],
    "Austria": ["Vienna", "Wien", "Graz", "Salzburg", "Innsbruck"],
    "Ireland": ["Dublin", "Cork", "Galway", "Limerick"],
    "Portugal": ["Lisbon", "Lisboa", "Porto"],
    "Sweden": ["Stockholm", "Gothenburg", "Göteborg", "Malmö"],
    "Norway": ["Oslo", "Bergen", "Trondheim", "Stavanger"],
    "Denmark": ["Copenhagen", "København", "Aarhus"],
    "Finland": ["Helsinki", "Espoo", "Tampere"],
    "Poland": ["Warsaw", "Warszawa", "Kraków", "Krakow", "Wrocław", "Wroclaw", "Gdańsk", "Gdansk", "Poznań"],
    "Czechia": ["Prague", "Praha", "Brno"],
    "Hungary": ["Budapest"], "Romania": ["Bucharest", "Cluj-Napoca"], "Bulgaria": ["Sofia"],
    "Greece": ["Athens", "Thessaloniki"], "Croatia": ["Zagreb"], "Slovenia": ["Ljubljana"], "Slovakia": ["Bratislava"],
    "Serbia": ["Belgrade", "Novi Sad"], "Bosnia and Herzegovina": ["Sarajevo"], "Montenegro": ["Podgorica"],
    "North Macedonia": ["Skopje"], "Albania": ["Tirana"], "Kosovo": ["Pristina", "Prishtina"],
    "Estonia": ["Tallinn"], "Latvia": ["Riga"], "Lithuania": ["Vilnius", "Kaunas"], "Luxembourg": [],
    "Iceland": ["Reykjavik", "Reykjavík"], "Malta": ["Valletta"], "Cyprus": ["Nicosia", "Limassol"],
    "Ukraine": ["Kyiv", "Kiev", "Lviv", "Odesa"], "Turkey": ["Istanbul", "İstanbul", "Ankara", "Izmir", "İzmir"], "Moldova": ["Chișinău", "Chisinau"],
}

# Explicit evidence of a location OUTSIDE the target markets.
OTHER_PLACES = re.compile(
    r"\b(?:USA|U\.S\.A?\.|United States|US-based|Canada|Australia|New Zealand|India|Pakistan|Bangladesh|"
    r"Philippines|Indonesia|Malaysia|Singapore|China|Japan|South Korea|Brazil|Mexico|Argentina|Colombia|Chile|"
    r"Nigeria|Kenya|South Africa|Egypt|Morocco|Saudi Arabia|Qatar|Kuwait|Bahrain|Oman|Israel|"
    r"Ohio|Texas|California|New York|Florida|Illinois|Toronto|Sydney|Melbourne|Mumbai|Bangalore|Delhi)\b")

ISO_TO_COUNTRY = {}
for _name, (_i2, _i3, _m, _f) in COUNTRIES.items():
    ISO_TO_COUNTRY[_i2] = _name
    ISO_TO_COUNTRY[_i3] = _name
ISO_TO_COUNTRY["UK"] = "United Kingdom"


def _name_regex() -> re.Pattern[str]:
    names = sorted(set(COUNTRIES) | {a for a in ALIASES}, key=len, reverse=True)
    # Country names case-insensitive, except ambiguous short ones handled case-sensitively below.
    safe = [n for n in names if n.lower() not in ("georgia", "turkey", "jersey", "uk", "uae")]
    return re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(n) for n in safe) + r")(?!\w)", re.I)


_NAMES_RX = _name_regex()
# Case-sensitive: "UK", "UAE", "Turkey" (not the bird), "Jersey" (not the garment) only as proper nouns.
_CASED_RX = re.compile(r"(?<![\w-])(UK|UAE|U\.K\.|U\.A\.E\.|Türkiye|Turkey(?=\s*(?:-based|based|,|\)|\.|$| office| company))|Jersey(?=,| Channel| office| company))(?!\w)")
_CITY_RX = re.compile(r"(?<![\w-])(" + "|".join(re.escape(c) for cs in CITIES.values() for c in sorted(cs, key=len, reverse=True)) + r")(?!\w)")
_CITY_TO_COUNTRY = {c: country for country, cs in CITIES.items() for c in cs}


@dataclass
class Location:
    country: str            # country name, "unknown" or "other:<evidence>"
    market: str             # UK / UAE / Europe / other / unknown
    evidence: str           # what in the source supports it
    flags: tuple[str, ...] = ()

    @property
    def in_target(self) -> bool:
        return self.market in TARGET_MARKETS


UNKNOWN = Location("unknown", "unknown", "no country or city named in the source")


def _loc(country: str, evidence: str) -> Location:
    _, _, market, flags = COUNTRIES[country]
    return Location(country, market, evidence, flags)


def from_code(code: Optional[str], evidence_prefix: str = "structured country code") -> Location:
    if not code:
        return UNKNOWN
    name = ISO_TO_COUNTRY.get(code.strip().upper())
    if name:
        return _loc(name, f"{evidence_prefix} '{code}'")
    return Location(f"other:{code}", "other", f"{evidence_prefix} '{code}'")


def detect(text: str) -> Location:
    """Find target-market place evidence in free text; else explicit out-of-market evidence; else unknown."""
    if not text:
        return UNKNOWN
    m = _CASED_RX.search(text)
    if m:
        tok = m.group(1).replace(".", "").upper()
        name = {"UK": "United Kingdom", "UAE": "United Arab Emirates"}.get(tok) or \
            ("Turkey" if m.group(1) in ("Turkey", "Türkiye") else "Jersey")
        return _loc(name, f"text mentions '{m.group(1)}'")
    m = _NAMES_RX.search(text)
    if m:
        raw = m.group(0)
        name = ALIASES.get(raw.lower()) or next((n for n in COUNTRIES if n.lower() == raw.lower()), None)
        if name:
            return _loc(name, f"text mentions '{raw}'")
    m = _CITY_RX.search(text)
    if m:
        return _loc(_CITY_TO_COUNTRY[m.group(1)], f"text mentions city '{m.group(1)}'")
    m = OTHER_PLACES.search(text)
    if m:
        return Location(f"other:{m.group(0)}", "other", f"text mentions '{m.group(0)}'")
    return UNKNOWN
