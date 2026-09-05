"""
Aggregate integrated_data_by_state.csv (the ONLY data source) into the
compact JSON payload consumed by the state -> county vulnerability map.

Produces map_data.json:
    {
      "generated_from": "...",
      "national": {...},
      "states": {
        "AL": {
          "fips", "name", "region",
          "population", "zcta_count", "county_count",
          "vulnerability": <0-100 population-weighted SDOH composite>,
          "components": {POV150, UNEMP, NOHSDP, BROAD, HCOST, CROWD, SNGPNT},
          "context": {REMNRTY, AGE65},
          "health": {ACCESS2, OBESITY, DIABETES, CSMOKING, CHECKUP, DENTAL},
          "counties": [
            {"name", "population", "zcta_count", "vulnerability",
             "components": {...}, "context": {...}, "health": {...}},
            ...
          ]
        },
        ...
      }
    }

Vulnerability = simple mean of seven population-weighted SDOH deprivation
measures (poverty, unemployment, no diploma, no broadband, housing cost
burden, crowding, single-parent households) -- all already expressed as
percentages, so no rescaling is applied. Demographic context (minority
share, 65+ share) and PLACES health measures are reported separately and
are NOT part of the composite.
"""

import json
import math
import pandas as pd

SOURCE_FILE = "integrated_data_by_state.csv"
OUTPUT_FILE = "map_data.json"

COMPOSITE_COLS = {
    "POV150": "SDOH_POV150",
    "UNEMP": "SDOH_UNEMP",
    "NOHSDP": "SDOH_NOHSDP",
    "BROAD": "SDOH_BROAD",
    "HCOST": "SDOH_HCOST",
    "CROWD": "SDOH_CROWD",
    "SNGPNT": "SDOH_SNGPNT",
}
CONTEXT_COLS = {
    "REMNRTY": "SDOH_REMNRTY",
    "AGE65": "SDOH_AGE65",
}
HEALTH_COLS = {
    "ACCESS2": "ACCESS2_CrudePrev",
    "OBESITY": "OBESITY_CrudePrev",
    "DIABETES": "DIABETES_CrudePrev",
    "CSMOKING": "CSMOKING_CrudePrev",
    "CHECKUP": "CHECKUP_CrudePrev",
    "DENTAL": "DENTAL_CrudePrev",
}

CENSUS_REGION = {
    **{s: "Northeast" for s in ["CT", "ME", "MA", "NH", "RI", "VT", "NJ", "NY", "PA"]},
    **{s: "Midwest" for s in ["IL", "IN", "MI", "OH", "WI", "IA", "KS", "MN", "MO", "NE", "ND", "SD"]},
    **{s: "South" for s in ["DE", "FL", "GA", "MD", "NC", "SC", "VA", "DC", "WV", "AL", "KY", "MS", "TN", "AR", "LA", "OK", "TX"]},
    **{s: "West" for s in ["AZ", "CO", "ID", "MT", "NV", "NM", "UT", "WY", "AK", "CA", "HI", "OR", "WA"]},
    **{s: "Territories" for s in ["PR", "GU", "VI", "AS", "MP"]},
}


def weighted_mean(values, weights):
    pairs = [(v, w) for v, w in zip(values, weights) if pd.notna(v) and pd.notna(w) and w > 0]
    if not pairs:
        return None
    total_w = sum(w for _, w in pairs)
    if total_w <= 0:
        return None
    return sum(v * w for v, w in pairs) / total_w


def round_or_none(x, ndigits=1):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    return round(x, ndigits)


def summarize_group(g):
    pop = g["TotalPopulation"]
    out = {
        "population": round_or_none(pop.sum(skipna=True), 0),
        "zcta_count": int(len(g)),
    }
    comp_vals = {}
    for key, col in COMPOSITE_COLS.items():
        m = weighted_mean(g[col], pop)
        comp_vals[key] = m
    present = [v for v in comp_vals.values() if v is not None]
    out["vulnerability"] = round_or_none(sum(present) / len(present), 1) if present else None
    out["components"] = {k: round_or_none(v) for k, v in comp_vals.items()}
    out["context"] = {k: round_or_none(weighted_mean(g[col], pop)) for k, col in CONTEXT_COLS.items()}
    out["health"] = {k: round_or_none(weighted_mean(g[col], pop)) for k, col in HEALTH_COLS.items()}
    return out


def main():
    needed = (
        ["STATE_FIPS", "STUSAB", "STATE_NAME", "COUNTY_NAME", "ZCTA5", "TotalPopulation"]
        + list(COMPOSITE_COLS.values())
        + list(CONTEXT_COLS.values())
        + list(HEALTH_COLS.values())
    )
    df = pd.read_csv(SOURCE_FILE, dtype={"STATE_FIPS": str, "ZCTA5": str}, usecols=needed)

    states_out = {}
    for stusab, sdf in df.groupby("STUSAB"):
        state_name = sdf["STATE_NAME"].iloc[0]
        state_fips = sdf["STATE_FIPS"].iloc[0]

        counties = []
        for county_name, cdf in sdf.groupby("COUNTY_NAME"):
            c_summary = summarize_group(cdf)
            c_summary["name"] = county_name
            counties.append(c_summary)
        counties.sort(key=lambda c: (-(c["vulnerability"] or -1)))

        state_summary = summarize_group(sdf)
        state_summary.update(
            {
                "fips": state_fips,
                "name": state_name,
                "region": CENSUS_REGION.get(str(stusab), "Territories"),
                "county_count": len(counties),
                "counties": counties,
            }
        )
        states_out[stusab] = state_summary

    national_pop = df["TotalPopulation"]
    national = summarize_group(df)
    national["state_count"] = len(states_out)

    payload = {
        "generated_from": SOURCE_FILE,
        "national": national,
        "states": states_out,
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(payload, f, separators=(",", ":"))

    import os

    print(f"States: {len(states_out)}")
    print(f"Total counties: {sum(s['county_count'] for s in states_out.values())}")
    print(f"National vulnerability composite: {national['vulnerability']}")
    print(f"Wrote {OUTPUT_FILE} ({os.path.getsize(OUTPUT_FILE) / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
