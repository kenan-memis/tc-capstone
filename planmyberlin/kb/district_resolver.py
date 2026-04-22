"""Resolve Berlin area labels to canonical boroughs and match candidates."""

from __future__ import annotations

import math
import re


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


# Canonical borough key for each UI area label (and common aliases).
AREA_TO_BOROUGH: dict[str, str] = {
    "alexanderplatz & mitte core": "mitte",
    "mitte (overall)": "mitte",
    "moabit & hansaviertel": "mitte",
    "tiergarten": "mitte",
    "charlottenburg": "charlottenburg_wilmersdorf",
    "wilmersdorf": "charlottenburg_wilmersdorf",
    "grunewald": "charlottenburg_wilmersdorf",
    "charlottenburg-wilmersdorf (overall)": "charlottenburg_wilmersdorf",
    "friedrichshain": "friedrichshain_kreuzberg",
    "kreuzberg": "friedrichshain_kreuzberg",
    "friedrichshain-kreuzberg (overall)": "friedrichshain_kreuzberg",
    "neukölln": "neukoelln",
    "nord-neukölln & reuterkiez": "neukoelln",
    "prenzlauer berg": "pankow",
    "niederschönhausen & pankow north": "pankow",
    "pankow (overall)": "pankow",
    "weißensee": "pankow",
    "wedding & gesundbrunnen": "mitte",
    "tempelhof & mariendorf": "tempelhof_schoeneberg",
    "schöneberg": "tempelhof_schoeneberg",
    "tempelhof-schöneberg (overall)": "tempelhof_schoeneberg",
    "spandau (overall)": "spandau",
    "dahlem & zehlendorf south": "steglitz_zehlendorf",
    "steglitz": "steglitz_zehlendorf",
    "treptow-köpenick (overall)": "treptow_koepenick",
    "köpenick & treptow": "treptow_koepenick",
    "karlshorst": "lichtenberg",
    "lichtenberg": "lichtenberg",
    "hohenschönhausen": "lichtenberg",
    "marzahn": "marzahn_hellersdorf",
    "hellersdorf": "marzahn_hellersdorf",
    "reinickendorf (overall)": "reinickendorf",
    "wittenau & reinickendorf north": "reinickendorf",
}

# Approximate center + radius per borough for coarse geo inclusion fallback.
BOROUGH_GEO_HINTS: dict[str, tuple[float, float, float]] = {
    "mitte": (52.5206, 13.3862, 4.8),
    "friedrichshain_kreuzberg": (52.5040, 13.4320, 4.2),
    "pankow": (52.5650, 13.4140, 7.0),
    "charlottenburg_wilmersdorf": (52.5010, 13.3040, 6.0),
    "spandau": (52.5350, 13.2000, 7.5),
    "steglitz_zehlendorf": (52.4450, 13.2900, 8.0),
    "tempelhof_schoeneberg": (52.4650, 13.3700, 5.0),
    "neukoelln": (52.4730, 13.4450, 5.5),
    "treptow_koepenick": (52.4450, 13.5750, 12.0),
    "marzahn_hellersdorf": (52.5400, 13.5800, 8.5),
    "lichtenberg": (52.5200, 13.5000, 6.0),
    "reinickendorf": (52.5900, 13.3300, 7.5),
}

# Coarse postcode-prefix fallback (Berlin 10xxx-14xxx).
PLZ3_TO_BOROUGH: dict[str, str] = {
    "101": "mitte",
    "102": "friedrichshain_kreuzberg",
    "103": "lichtenberg",
    "104": "pankow",
    "105": "mitte",
    "106": "charlottenburg_wilmersdorf",
    "107": "tempelhof_schoeneberg",
    "108": "tempelhof_schoeneberg",
    "109": "friedrichshain_kreuzberg",
    "120": "neukoelln",
    "121": "steglitz_zehlendorf",
    "122": "steglitz_zehlendorf",
    "123": "neukoelln",
    "124": "treptow_koepenick",
    "125": "treptow_koepenick",
    "126": "marzahn_hellersdorf",
    "130": "pankow",
    "131": "pankow",
    "133": "mitte",
    "134": "reinickendorf",
    "135": "spandau",
    "136": "spandau",
    "140": "charlottenburg_wilmersdorf",
}


def canonical_borough(area: str) -> str:
    n = _norm(area)
    if n in AREA_TO_BOROUGH:
        return AREA_TO_BOROUGH[n]
    return re.sub(r"[^a-z0-9]+", "_", n).strip("_") or "unknown"


def extract_postal_code(address: str) -> str | None:
    m = re.search(r"\b(1\d{4})\b", address or "")
    return m.group(1) if m else None


def borough_from_postal_code(postal_code: str | None) -> str | None:
    if not postal_code or len(postal_code) < 3:
        return None
    return PLZ3_TO_BOROUGH.get(postal_code[:3])


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


def candidate_matches_area(
    area: str,
    *,
    address: str,
    latitude: float | None,
    longitude: float | None,
) -> bool:
    """Area match strategy: text hints -> postal-code borough -> geo-radius borough."""
    area_norm = _norm(area)
    addr_norm = _norm(address)
    if area_norm and area_norm in addr_norm:
        return True

    borough = canonical_borough(area)
    if borough in addr_norm:
        return True

    plz_borough = borough_from_postal_code(extract_postal_code(address))
    if plz_borough and plz_borough == borough:
        return True

    hint = BOROUGH_GEO_HINTS.get(borough)
    if hint and latitude is not None and longitude is not None:
        c_lat, c_lng, radius_km = hint
        if _haversine_km(c_lat, c_lng, latitude, longitude) <= radius_km:
            return True

    return False
