"""Populate IMIS.dbo.PVD.cpi from IMIS.dbo.CPI_CITY.

The script is deliberately dry-run by default. Pass ``--apply`` to commit.
It is idempotent and refuses to overwrite a different nonzero CPI mapping.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from sqlalchemy import bindparam, text

from pricelab.integration.sql_export import _engine


@dataclass(frozen=True)
class CityDistrictMapping:
    city_code: int
    city_name: str
    district_ids: tuple[str, ...]
    rationale: str = "name match"


MAPPINGS = (
    CityDistrictMapping(1, "Rawalpindi", ("054",)),
    CityDistrictMapping(2, "Islamabad", ("128",)),
    CityDistrictMapping(3, "Attock", ("051",)),
    CityDistrictMapping(4, "Lahore", ("044",)),
    CityDistrictMapping(5, "Sahiwal", ("057",)),
    CityDistrictMapping(6, "Gujranwala", ("037",)),
    CityDistrictMapping(7, "Sialkot", ("042",)),
    CityDistrictMapping(8, "Faisalabad", ("034",)),
    CityDistrictMapping(9, "Jhang", ("035",)),
    CityDistrictMapping(10, "Multan", ("049",)),
    CityDistrictMapping(11, "D. G. Khan", ("029",), "Dera Ghazi Khan abbreviation"),
    CityDistrictMapping(12, "Vehari", ("050",)),
    CityDistrictMapping(13, "Sargodha", ("061",)),
    CityDistrictMapping(14, "Mianwali", ("060",)),
    CityDistrictMapping(15, "Bahawalpur", ("027",)),
    CityDistrictMapping(16, "Bahawalnagar", ("026",)),
    CityDistrictMapping(17, "Rahim Yar Khan", ("028",), "canonical city and district name"),
    CityDistrictMapping(
        18,
        "Karachi",
        ("146", "147", "148", "149", "150", "154", "166"),
        "one CPI price centre covers every district in Karachi Division",
    ),
    CityDistrictMapping(19, "Hyderabad", ("064",)),
    CityDistrictMapping(20, "Nawabshah", ("083",), "renamed Shaheed Benazirabad District"),
    CityDistrictMapping(21, "Mirpukhas", ("076",), "Mirpur Khas spelling variant"),
    CityDistrictMapping(22, "Sukkur", ("084",)),
    CityDistrictMapping(23, "Larkana", ("073",)),
    CityDistrictMapping(24, "Dadu", ("063",)),
    CityDistrictMapping(25, "Peshawar", ("025",)),
    CityDistrictMapping(26, "Abbottabad", ("005",)),
    CityDistrictMapping(27, "Bannu", ("001",)),
    CityDistrictMapping(28, "D. I. Khan", ("003",), "Dera Ismail Khan abbreviation"),
    CityDistrictMapping(29, "Mingora", ("019",), "city in Swat District"),
    CityDistrictMapping(30, "Quetta", ("103",)),
    CityDistrictMapping(31, "Turbat", ("093",), "city in Kech District"),
    CityDistrictMapping(32, "Gawadar", ("092",), "Gwadar spelling variant"),
    CityDistrictMapping(33, "Loralai", ("111",)),
    CityDistrictMapping(34, "Khuzdar", ("088",)),
    CityDistrictMapping(35, "D. M. Jamali", ("098",), "Dera Murad Jamali in Nasirabad District"),
)


def _normalise_city_name(value: str) -> str:
    return value.strip().casefold()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="commit the validated mappings (otherwise perform a dry run)",
    )
    args = parser.parse_args()

    expected_codes = {mapping.city_code for mapping in MAPPINGS}
    target_ids = [district_id for mapping in MAPPINGS for district_id in mapping.district_ids]
    if expected_codes != set(range(1, 36)):
        raise RuntimeError("The manifest must cover CPI city codes 1 through 35 exactly once.")
    if len(target_ids) != len(set(target_ids)):
        raise RuntimeError("A district appears more than once in the mapping manifest.")

    engine = _engine()
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
                database_name = connection.execute(text("SELECT DB_NAME()" )).scalar_one()
                if database_name.casefold() != "imis":
                    raise RuntimeError(f"Refusing to modify database {database_name!r}; IMIS is required.")

                city_rows = connection.execute(
                    text("SELECT CityCode, CityName FROM dbo.CPI_CITY WITH (UPDLOCK, HOLDLOCK)")
                ).mappings()
                cities = {int(row["CityCode"]): str(row["CityName"]) for row in city_rows}
                if set(cities) != expected_codes:
                    raise RuntimeError(
                        f"CPI_CITY codes changed: expected {sorted(expected_codes)}, got {sorted(cities)}"
                    )
                for mapping in MAPPINGS:
                    if _normalise_city_name(cities[mapping.city_code]) != _normalise_city_name(mapping.city_name):
                        raise RuntimeError(
                            f"CPI_CITY name mismatch for {mapping.city_code:02d}: "
                            f"expected {mapping.city_name!r}, got {cities[mapping.city_code]!r}"
                        )

                district_rows = connection.execute(
                    text(
                        "SELECT dsid, ds, cpi FROM dbo.PVD WITH (UPDLOCK, HOLDLOCK) "
                        "WHERE dsid IN :district_ids"
                    ).bindparams(bindparam("district_ids", expanding=True)),
                    {"district_ids": target_ids},
                ).mappings()
                districts = {str(row["dsid"]): row for row in district_rows}
                missing = sorted(set(target_ids) - set(districts))
                if missing:
                    raise RuntimeError(f"PVD target districts are missing: {missing}")

                for mapping in MAPPINGS:
                    for district_id in mapping.district_ids:
                        existing = int(districts[district_id]["cpi"])
                        if existing not in (0, mapping.city_code):
                            raise RuntimeError(
                                f"Refusing to overwrite PVD {district_id} ({districts[district_id]['ds']}): "
                                f"existing cpi={existing}, proposed cpi={mapping.city_code}"
                            )

                print("MODE:", "APPLY" if args.apply else "DRY RUN")
                print("CityCode\tCityName\tDistrictId\tDistrict\tRationale\tCurrent")
                for mapping in MAPPINGS:
                    for district_id in mapping.district_ids:
                        row = districts[district_id]
                        print(
                            f"{mapping.city_code:02d}\t{cities[mapping.city_code]}\t{district_id}\t"
                            f"{row['ds']}\t{mapping.rationale}\t{row['cpi']}"
                        )

                if args.apply:
                    update = text(
                        "UPDATE dbo.PVD SET cpi=:city_code "
                        "WHERE dsid=:district_id AND cpi=0"
                    )
                    for mapping in MAPPINGS:
                        for district_id in mapping.district_ids:
                            connection.execute(
                                update,
                                {"city_code": mapping.city_code, "district_id": district_id},
                            )

                    verified = connection.execute(
                        text(
                            "SELECT dsid, cpi FROM dbo.PVD "
                            "WHERE dsid IN :district_ids"
                        ).bindparams(bindparam("district_ids", expanding=True)),
                        {"district_ids": target_ids},
                    ).mappings()
                    actual = {str(row["dsid"]): int(row["cpi"]) for row in verified}
                    expected = {
                        district_id: mapping.city_code
                        for mapping in MAPPINGS
                        for district_id in mapping.district_ids
                    }
                    if actual != expected:
                        raise RuntimeError("Post-update verification failed; transaction will be rolled back.")
                    transaction.commit()
                    print(f"Committed and verified {len(expected)} district mappings for 35 CPI cities.")
                else:
                    transaction.rollback()
                    print(f"Validated {len(target_ids)} target districts; no changes were made.")
            except Exception:
                if transaction.is_active:
                    transaction.rollback()
                raise
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
