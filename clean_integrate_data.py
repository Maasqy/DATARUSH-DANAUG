"""
Clean and integrate the four DATARUSH-DANAUG source CSVs into a single
dataset organized by state.

Sources (all in this folder):
    STATESDAT-f_Data.csv        state FIPS -> abbreviation / name lookup
    COUNTYDAT-f_Data.csv        ZCTA5 -> county (and therefore state) lookup
    PLACES_f-ZCTA5_Data.csv     health-measure prevalence estimates by ZCTA5
    SDOH_f-Measures_Data.csv    social-determinants-of-health measures by ZCTA5 (long format)

Output:
    integrated_data_by_state.csv
    One row per ZCTA5, tagged with its state, sorted by state then ZCTA5.
"""

import re
import pandas as pd

STATES_FILE = "STATESDAT-f_Data.csv"
COUNTY_FILE = "COUNTYDAT-f_Data.csv"
PLACES_FILE = "PLACES_f-ZCTA5_Data.csv"
SDOH_FILE = "SDOH_f-Measures_Data.csv"
OUTPUT_FILE = "integrated_data_by_state.csv"


def load_states():
    """State FIPS -> abbreviation / full name lookup."""
    states = pd.read_csv(STATES_FILE, dtype=str)
    states = states.rename(columns={"STATE": "STATE_FIPS"})
    return states[["STATE_FIPS", "STUSAB", "STATE_NAME"]].drop_duplicates()


def load_zcta_state_map(states):
    """ZCTA5 -> state (via county FIPS) lookup, one row per ZCTA5."""
    county = pd.read_csv(COUNTY_FILE, dtype=str)
    county = county.rename(
        columns={
            "GEOID_ZCTA5_20": "ZCTA5",
            "NAMELSAD_COUNTY_20": "COUNTY_NAME",
        }
    )
    county["STATE_FIPS"] = county["GEOID_COUNTY_20"].str[:2]
    county = county.drop_duplicates(subset="ZCTA5")

    zcta_state = county.merge(states, on="STATE_FIPS", how="left")
    return zcta_state[["ZCTA5", "STATE_FIPS", "STUSAB", "STATE_NAME", "COUNTY_NAME"]]


def clean_ci_text(value):
    """Collapse internal whitespace in confidence-interval strings, e.g. '( 3.4,  4.5)' -> '(3.4, 4.5)'."""
    if pd.isna(value):
        return value
    return re.sub(r"\s+", " ", value.strip())


def load_places():
    """Clean the PLACES ZCTA5-level health-measure prevalence data."""
    places = pd.read_csv(PLACES_FILE, dtype=str)
    places = places.rename(columns={"ZCTA5": "ZCTA5"})
    places["ZCTA5"] = places["ZCTA5"].str.zfill(5)

    for col in places.columns:
        if col == "ZCTA5":
            continue
        if col.endswith("_CrudePrev"):
            places[col] = pd.to_numeric(places[col], errors="coerce")
        elif col.endswith("_Crude95CI"):
            places[col] = places[col].apply(clean_ci_text)

    return places.drop_duplicates(subset="ZCTA5")


def load_sdoh():
    """Pivot the long-format SDOH measures into one row per ZCTA5."""
    sdoh = pd.read_csv(
        SDOH_FILE,
        dtype=str,
        usecols=[
            "LocationID",
            "MeasureID",
            "Data_Value",
            "TotalPopulation",
            "Geolocation",
        ],
    )
    sdoh = sdoh.rename(columns={"LocationID": "ZCTA5"})
    sdoh["ZCTA5"] = sdoh["ZCTA5"].str.zfill(5)
    sdoh["Data_Value"] = pd.to_numeric(sdoh["Data_Value"], errors="coerce")
    sdoh["TotalPopulation"] = pd.to_numeric(
        sdoh["TotalPopulation"].str.replace(",", "", regex=False), errors="coerce"
    )

    # one population/geolocation value per ZCTA5 (constant across its measure rows)
    location_info = (
        sdoh[["ZCTA5", "TotalPopulation", "Geolocation"]]
        .drop_duplicates(subset="ZCTA5")
        .set_index("ZCTA5")
    )

    wide = sdoh.pivot_table(
        index="ZCTA5", columns="MeasureID", values="Data_Value", aggfunc="first"
    )
    wide.columns = [f"SDOH_{c}" for c in wide.columns]

    sdoh_wide = wide.join(location_info).reset_index()
    return sdoh_wide


def main():
    states = load_states()
    zcta_state = load_zcta_state_map(states)
    places = load_places()
    sdoh_wide = load_sdoh()

    print(f"States lookup:        {len(states)} rows")
    print(f"ZCTA5 -> state map:   {len(zcta_state)} rows")
    print(f"PLACES measures:      {len(places)} rows")
    print(f"SDOH measures (wide): {len(sdoh_wide)} rows")

    # zcta_state is the backbone: every output row needs a known state.
    integrated = zcta_state.merge(places, on="ZCTA5", how="left")
    integrated = integrated.merge(sdoh_wide, on="ZCTA5", how="left")

    dropped_no_state = zcta_state["STATE_NAME"].isna().sum()
    if dropped_no_state:
        print(f"Warning: {dropped_no_state} ZCTA5 rows had no matching state and were excluded.")
    integrated = integrated.dropna(subset=["STATE_NAME"])

    integrated = integrated.sort_values(["STATE_NAME", "ZCTA5"]).reset_index(drop=True)

    integrated.to_csv(OUTPUT_FILE, index=False)
    print(f"\nWrote {len(integrated)} rows x {len(integrated.columns)} columns to {OUTPUT_FILE}")
    print(f"States represented: {integrated['STATE_NAME'].nunique()}")


if __name__ == "__main__":
    main()
