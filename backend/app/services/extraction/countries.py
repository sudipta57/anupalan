"""Country names, for recognising that a country-of-origin reading actually names a country.

**Why a list, when "is it India?" needed none.** Prefill proposes ``is_imported`` from a
pattern-matched "Country of origin ..." line (``extraction.prefill``). "Not India" is a *negative*
test, so any misread passes it: OCR has turned "DABUR INDIA" into ``DABURNDIAID``, and a pattern
on "made in" will happily capture "a facility that also handles nuts". Either would propose a
domestic pack as imported, which turns on the importer rules and FAILs a compliant label — the
expensive direction to be wrong in (CLAUDE.md §3.4). A positive test does not have that hole: the
reading has to *name a country* before its not being India means anything.

**Incomplete in the safe direction.** A country missing from here, or a name OCR has mangled
("Nepa"), proposes nothing and the form's own default stands. It can never propose imported for a
string that is not on the list. So the list is kept generous — every UN member state, plus the
names and abbreviations labels actually print — without needing to be perfect.

A vocabulary, not legal content: no threshold, table row or date is encoded here (CLAUDE.md §3.2).
Entries are lowercased with punctuation folded to single spaces, the form ``prefill._cleaned``
produces, so "U.S.A." is stored as "u s a".
"""

from __future__ import annotations

# A vocabulary reads better as a block than as 240 one-word lines.
# fmt: off
COUNTRY_NAMES: frozenset[str] = frozenset(
    {
        "afghanistan", "albania", "algeria", "andorra", "angola", "antigua and barbuda",
        "argentina", "armenia", "australia", "austria", "azerbaijan", "bahamas", "bahrain",
        "bangladesh", "barbados", "belarus", "belgium", "belize", "benin", "bhutan", "bolivia",
        "bosnia and herzegovina", "botswana", "brazil", "brunei", "bulgaria", "burkina faso",
        "burundi", "cabo verde", "cambodia", "cameroon", "canada", "central african republic",
        "chad", "chile", "china", "colombia", "comoros", "congo", "costa rica", "cote d ivoire",
        "croatia", "cuba", "cyprus", "czechia", "denmark", "djibouti", "dominica",
        "dominican republic", "ecuador", "egypt", "el salvador", "equatorial guinea", "eritrea",
        "estonia", "eswatini", "ethiopia", "fiji", "finland", "france", "gabon", "gambia",
        "georgia", "germany", "ghana", "greece", "grenada", "guatemala", "guinea",
        "guinea bissau", "guyana", "haiti", "honduras", "hungary", "iceland", "india",
        "indonesia", "iran", "iraq", "ireland", "israel", "italy", "jamaica", "japan", "jordan",
        "kazakhstan", "kenya", "kiribati", "kuwait", "kyrgyzstan", "laos", "latvia", "lebanon",
        "lesotho", "liberia", "libya", "liechtenstein", "lithuania", "luxembourg", "madagascar",
        "malawi", "malaysia", "maldives", "mali", "malta", "marshall islands", "mauritania",
        "mauritius", "mexico", "micronesia", "moldova", "monaco", "mongolia", "montenegro",
        "morocco", "mozambique", "myanmar", "namibia", "nauru", "nepal", "netherlands",
        "new zealand", "nicaragua", "niger", "nigeria", "north korea", "north macedonia",
        "norway", "oman", "pakistan", "palau", "panama", "papua new guinea", "paraguay", "peru",
        "philippines", "poland", "portugal", "qatar", "romania", "russia", "rwanda",
        "saint kitts and nevis", "saint lucia", "saint vincent and the grenadines", "samoa",
        "san marino", "sao tome and principe", "saudi arabia", "senegal", "serbia",
        "seychelles", "sierra leone", "singapore", "slovakia", "slovenia", "solomon islands",
        "somalia", "south africa", "south korea", "south sudan", "spain", "sri lanka", "sudan",
        "suriname", "sweden", "switzerland", "syria", "tajikistan", "tanzania", "thailand",
        "timor leste", "togo", "tonga", "trinidad and tobago", "tunisia", "turkey", "turkiye",
        "turkmenistan", "tuvalu", "uganda", "ukraine", "united arab emirates", "united kingdom",
        "united states", "united states of america", "uruguay", "uzbekistan", "vanuatu",
        "venezuela", "vietnam", "viet nam", "yemen", "zambia", "zimbabwe",
        # Names and abbreviations labels print that are not the UN short name.
        "usa", "u s a", "us", "u s", "uk", "u k", "uae", "u a e", "england", "scotland", "wales",
        "great britain", "britain", "holland", "korea", "republic of korea", "czech republic",
        "ivory coast", "burma", "hong kong", "taiwan", "macau", "macao", "prc", "p r c",
        "people s republic of china", "swaziland", "cape verde", "east timor", "lao pdr",
        "russian federation", "the netherlands", "bharat",
    }
)
# fmt: on
"""Lowercased, punctuation-folded country names. Includes India and Bharat: the caller asks "which
country is named" and then "is it India", and both questions need India to be recognisable."""

LONGEST_NAME_WORDS = max(len(name.split()) for name in COUNTRY_NAMES)
"""How many leading words a reading can need before it is known to name no country."""

INDIA_NAMES: frozenset[str] = frozenset({"india", "bharat"})


def country_named(cleaned: str) -> str | None:
    """The country a cleaned reading *starts* with, or None.

    Leading words only, longest match first. The pattern captures whatever follows "Country of
    origin", which on a real label runs on into the next line — ``"nepal net quantity 180ml"`` — so
    the country is the reading's prefix, and a country named later in the string is not the one the
    declaration is about.
    """
    words = cleaned.split()
    for count in range(min(LONGEST_NAME_WORDS, len(words)), 0, -1):
        candidate = " ".join(words[:count])
        if candidate in COUNTRY_NAMES:
            return candidate
    return None


__all__ = ["COUNTRY_NAMES", "INDIA_NAMES", "LONGEST_NAME_WORDS", "country_named"]
