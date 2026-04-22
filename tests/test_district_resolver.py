from planmyberlin.kb.district_resolver import (
    borough_from_postal_code,
    candidate_matches_area,
    canonical_borough,
    extract_postal_code,
)


def test_canonical_borough_maps_ui_label() -> None:
    assert canonical_borough("Alexanderplatz & Mitte core") == "mitte"
    assert canonical_borough("Friedrichshain-Kreuzberg (overall)") == "friedrichshain_kreuzberg"


def test_extract_postal_code_and_borough() -> None:
    code = extract_postal_code("Kurfürstenstraße 79, 10787 Berlin, Germany")
    assert code == "10787"
    assert borough_from_postal_code(code) == "tempelhof_schoeneberg"


def test_candidate_matches_area_on_postal_or_geo() -> None:
    assert candidate_matches_area(
        "Tiergarten",
        address="Potsdamer Str. 1, 10785 Berlin, Germany",
        latitude=52.5097,
        longitude=13.3758,
    )
