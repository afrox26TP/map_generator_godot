from textwrap import dedent

BATCHES = {
    "b1_core": ["Q142", "Q183", "Q38", "Q29", "Q45"],
    "b2_benelux_alps": ["Q31", "Q55", "Q32", "Q39", "Q40"],
    "b3_nordics": ["Q145", "Q27", "Q189", "Q20", "Q34", "Q35"],
    "b4_baltic_pl": ["Q33", "Q191", "Q211", "Q37", "Q36"],
    "b5_central": ["Q213", "Q214", "Q28", "Q215", "Q224", "Q225"],
    "b6_balkan": ["Q403", "Q236", "Q1246", "Q221", "Q222"],
    "b7_se_eu": ["Q41", "Q229", "Q219", "Q218", "Q217"],
    "b8_east": ["Q212", "Q184", "Q159"],
    "b9_caucasus": ["Q43", "Q230", "Q399", "Q227"],
    "b10_micro": ["Q228", "Q233", "Q347", "Q238", "Q235", "Q237"],
}

SPARQL_TEMPLATE = dedent(
    """
    SELECT ?region ?regionLabel ?iso ?country ?countryLabel ?isoA2 ?isoA3 ?population ?date WHERE {{
      {{
        SELECT ?region ?country (SAMPLE(?iso) AS ?iso) (MAX(?pDate) AS ?date) (SAMPLE(?pVal) AS ?population) WHERE {{
          VALUES ?country {{ {countries} }}
          ?region wdt:P31/wdt:P279* wd:Q10864048;
                  wdt:P300 ?iso;
                  wdt:P17 ?country.
          FILTER CONTAINS(?iso, "-")  # ISO 3166-2 only
          ?region p:P1082 ?popStmt.
          ?popStmt ps:P1082 ?pVal.
          OPTIONAL {{ ?popStmt pq:P585 ?pDate. }}
        }}
        GROUP BY ?region ?country
      }}
      OPTIONAL {{ ?country wdt:P297 ?isoA2. }}
      OPTIONAL {{ ?country wdt:P298 ?isoA3. }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}
    """
)


def make_query(batch_key: str) -> str:
    if batch_key not in BATCHES:
        raise KeyError(f"Unknown batch '{batch_key}'")
    countries = " ".join(f"wd:{q}" for q in BATCHES[batch_key])
    return SPARQL_TEMPLATE.format(countries=countries)


def main():
    for key in BATCHES:
        print(f"--- {key} ---")
        print(make_query(key))


if __name__ == "__main__":
    main()
