from planmyberlin.itinerary.grounding import (
    candidate_name_allowlist,
    find_grounding_violations,
    sanitize_place_names,
)
from planmyberlin.itinerary.models import TripItinerary


def test_find_violations_unknown_venue() -> None:
    allowed_norm, norm_to_canonical = candidate_name_allowlist(
        [{"name": "Museum Island", "category": "places"}]
    )
    it = TripItinerary.model_validate(
        {
            "title": "T",
            "days": [
                {
                    "day_number": 1,
                    "theme": "x",
                    "activities": [
                        {
                            "time_of_day": "morning",
                            "title": "Visit",
                            "description": "d",
                            "place_name": "Completely Fake Venue XYZ",
                        }
                    ],
                }
            ],
            "practical_notes": [],
        }
    )
    v = find_grounding_violations(it, allowed_norm)
    assert len(v) == 1


def test_sanitize_clears_bad_name() -> None:
    allowed_norm, norm_to_canonical = candidate_name_allowlist([{"name": "Museum Island"}])
    it = TripItinerary.model_validate(
        {
            "title": "T",
            "days": [
                {
                    "day_number": 1,
                    "theme": "x",
                    "activities": [
                        {
                            "time_of_day": "morning",
                            "title": "Visit",
                            "description": "d",
                            "place_name": "Fake",
                        }
                    ],
                }
            ],
            "practical_notes": [],
        }
    )
    fixed = sanitize_place_names(it, allowed_norm, norm_to_canonical)
    assert fixed.days[0].activities[0].place_name is None


def test_fuzzy_match_keeps_canonical() -> None:
    allowed_norm, norm_to_canonical = candidate_name_allowlist([{"name": "Museum Island"}])
    it = TripItinerary.model_validate(
        {
            "title": "T",
            "days": [
                {
                    "day_number": 1,
                    "theme": "x",
                    "activities": [
                        {
                            "time_of_day": "morning",
                            "title": "Visit",
                            "description": "d",
                            "place_name": "museum island",
                        }
                    ],
                }
            ],
            "practical_notes": [],
        }
    )
    fixed = sanitize_place_names(it, allowed_norm, norm_to_canonical)
    assert fixed.days[0].activities[0].place_name == "Museum Island"
