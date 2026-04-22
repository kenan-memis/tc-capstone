from planmyberlin.kb.google_places_seed import (
    district_matches_address,
    district_matches_candidate,
    slugify,
)


def test_slugify_normalizes_unicode_and_spaces() -> None:
    assert slugify("Prenzlauer Berg") == "prenzlauer_berg"
    assert slugify("Schöneberg / Tempelhof") == "sch_neberg_tempelhof"


def test_district_matches_address_true_on_direct_match() -> None:
    assert district_matches_address("Kreuzberg", "Skalitzer Str. 95, 10997 Berlin-Kreuzberg")


def test_district_matches_address_false_without_explicit_area_text() -> None:
    assert not district_matches_address("Tiergarten", "Invalidenstraße 116, 10115 Berlin Mitte")


def test_district_matches_address_false_when_mismatch() -> None:
    assert not district_matches_address("Tiergarten", "Warschauer Str. 43, 10243 Berlin-Friedrichshain")


def test_district_matches_candidate_true_on_geo_hint() -> None:
    assert district_matches_candidate(
        "Tiergarten",
        address="Potsdamer Platz 2, 10785 Berlin, Germany",
        latitude=52.5097,
        longitude=13.3758,
    )
