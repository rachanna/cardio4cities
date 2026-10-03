"""Spike S-2: which official endpoints serve the Wave 0 indicators (BUILD_PLAN §2, BD-13).
No spend; public APIs only, within their published terms.

For WHO GHO: finds the hypertension, diabetes and premature-NCD-mortality indicators and,
for each chosen code, records its sex and age dimensions, the latest year and whether the
values are crude or age-standardised. For DHS: searches the indicator catalogue for
hypertension or blood-pressure indicators and checks that sub-national values are
returned. For the World Bank: confirms the population indicator.

Countries are given on the command line (ISO3, with the DHS two-letter code), so none is
written into the repository. Raw responses and a summary go to `spike_results/`, which
git ignores; the decision row summarises them.

    uv run python -m scripts.spikes.structured_endpoints AAA:AA BBB:BB CCC:CC   # ISO3:DHS codes
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx

OUT = Path(__file__).resolve().parents[2] / "spike_results"
GHO = "https://ghoapi.azureedge.net/api/"
DHS = "https://api.dhsprogram.com/rest/dhs/"
WB = "https://api.worldbank.org/v2/"
UA = {"user-agent": "CARDIO4CitiesResearchBot/0.1 (spike S-2)"}
GHO_TERMS = ["hypertension", "diabetes", "raised blood pressure", "raised fasting", "NCD mortality"]
GHO_CODES = [
    "NCD_HYP_PREVALENCE_A",
    "NCD_HYP_DIAGNOSIS_A",
    "NCD_HYP_TREATMENT_A",
    "NCD_HYP_CONTROL_A",
    "NCD_DIABETES_PREVALENCE_AGESTD",
    "NCDMORT3070",
]
DHS_TERMS = ["hypertens", "blood pressure", "systolic", "diastolic", "antihypert", "diabet"]


def get(client: httpx.Client, url: str, **params: Any) -> Any:
    response = client.get(url, params=params, timeout=120)
    response.raise_for_status()
    return response.json()


def gho(client: httpx.Client, iso3: list[str]) -> dict[str, Any]:
    found = {}
    for term in GHO_TERMS:
        rows = get(client, GHO + "Indicator", **{"$filter": f"contains(IndicatorName,'{term}')"})
        found[term] = [(r["IndicatorCode"], r["IndicatorName"]) for r in rows["value"]]
    codes = {}
    country_filter = " or ".join(f"SpatialDim eq '{c}'" for c in iso3)
    for code in GHO_CODES:
        rows = get(client, GHO + code, **{"$filter": country_filter})["value"]
        (OUT / f"gho_{code}.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
        codes[code] = {
            "sexes": sorted({r["Dim1"] for r in rows}),
            "age_groups": sorted(
                {str(r.get("Dim2")) for r in rows if r.get("Dim2Type") == "AGEGROUP"}
            ),
            "latest_year": {
                c: max((r["TimeDim"] for r in rows if r["SpatialDim"] == c), default=None)
                for c in iso3
            },
            "example": next((r["Value"] for r in rows if r["Dim1"] == "SEX_BTSX"), None),
        }
    return {"search": found, "codes": codes}


def dhs(client: httpx.Client, dhs_codes: list[str]) -> dict[str, Any]:
    catalogue = get(
        client,
        DHS + "indicators",
        f="json",
        perpage=5000,
        returnFields="IndicatorId,Label,Definition,Level1",
    )["Data"]
    hits = [
        d
        for d in catalogue
        if any(t in f"{d['Label']} {d['Definition']}".lower() for t in DHS_TERMS)
    ]
    sub = get(
        client,
        DHS + "data",
        countryIds=",".join(dhs_codes),
        indicatorIds="AN_NUTS_W_OWT",
        breakdown="subnational",
        f="json",
        perpage=1000,
        returnFields="CountryName,SurveyYear,CharacteristicCategory",
    )["Data"]
    return {
        "catalogue_size": len(catalogue),
        "blood_pressure_or_diabetes_hits": [(d["IndicatorId"], d["Label"]) for d in hits],
        "subnational_rows_for_a_sample_indicator": len(sub),
        "subnational_categories": sorted({r["CharacteristicCategory"] for r in sub}),
        "latest_survey": {
            r["CountryName"]: max(
                x["SurveyYear"] for x in sub if x["CountryName"] == r["CountryName"]
            )
            for r in sub
        },
    }


def world_bank(client: httpx.Client, iso3: list[str]) -> list[Any]:
    rows = get(client, WB + f"country/{';'.join(iso3)}/indicator/SP.POP.TOTL", format="json", mrv=1)
    return [(r["countryiso3code"], r["date"], r["value"]) for r in rows[1]]


def main(pairs: list[str]) -> int:
    iso3 = [p.split(":")[0] for p in pairs]
    dhs_codes = [p.split(":")[1] for p in pairs]
    OUT.mkdir(exist_ok=True)
    with httpx.Client(headers=UA, follow_redirects=True) as client:
        summary: dict[str, Any] = {
            "who_gho": gho(client, iso3),
            "dhs": dhs(client, dhs_codes),
            "world_bank": world_bank(client, iso3),
        }
    (OUT / "S-2-summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary["who_gho"]["codes"], indent=1))
    print(
        "DHS blood-pressure or diabetes indicators:",
        summary["dhs"]["blood_pressure_or_diabetes_hits"],
    )
    print(f"summary written to {OUT / 'S-2-summary.json'} (git-ignored)")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("countries", nargs=3, metavar="ISO3:DHS", help="e.g. AAA:AA")
    sys.exit(main(parser.parse_args().countries))
