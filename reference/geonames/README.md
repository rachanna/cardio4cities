# GeoNames gazetteer

The gazetteer behind city disambiguation (LLD-1 §3.1) comes from
[GeoNames](https://www.geonames.org/), licensed under
[Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/).

`uv run poe reference` downloads these files here when they are missing, then loads them:

| File | From | Loaded into |
|---|---|---|
| `cities15000.zip` | https://download.geonames.org/export/dump/cities15000.zip | `ref_place` |
| `admin1CodesASCII.txt` | https://download.geonames.org/export/dump/admin1CodesASCII.txt | `ref_admin1` |
| `countryInfo.txt` | https://download.geonames.org/export/dump/countryInfo.txt | `ref_country` |

`uv run poe geonames` downloads without loading. The files are git-ignored; delete
them to fetch a fresh copy. Loading is idempotent.

The data is used as published, except that country languages are reduced to
ISO 639-1 codes (`en-US` becomes `en`; three-letter codes are dropped), as
`CityIdentity.languages` expects.
