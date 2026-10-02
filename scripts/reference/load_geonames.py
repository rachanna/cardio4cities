"""Download GeoNames if missing and load it into ref_country, ref_admin1, ref_place.

    python -m scripts.reference.load_geonames [--download-only] [--force-download]

Idempotent: a second run reports zero inserted, updated and deleted rows.
"""

import argparse
import asyncio
import sys

from scripts.reference._db import relational_from_env
from scripts.reference.geonames import GEONAMES_DIR, download, read_gazetteer


async def load() -> None:
    gazetteer = read_gazetteer(GEONAMES_DIR)
    relational = relational_from_env()
    try:
        results = await relational.reference.sync_gazetteer(
            gazetteer.countries, gazetteer.admin1, gazetteer.places
        )
    finally:
        await relational.close()
    for result in results:
        print(result)
    if gazetteer.skipped_admin1 or gazetteer.skipped_places:
        print(
            f"skipped rows with a country missing from countryInfo: "
            f"{gazetteer.skipped_admin1} admin1, {gazetteer.skipped_places} places"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--download-only", action="store_true")
    parser.add_argument("--force-download", action="store_true")
    args = parser.parse_args(argv)

    for path in download(GEONAMES_DIR, force=args.force_download):
        print(f"downloaded {path.name}")
    if not args.download_only:
        asyncio.run(load())
    return 0


if __name__ == "__main__":
    sys.exit(main())
