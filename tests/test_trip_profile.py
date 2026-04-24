import pytest
from datetime import date

from planmyberlin.config.loader import get_interest_options
from planmyberlin.models.trip_profile import TripProfile


def test_trip_profile_defaults_need_explicit_dietary_mobility() -> None:
    """TripProfile requires dietary and mobility choices from YAML lists."""
    with pytest.raises(Exception):
        TripProfile(days=2, include_accommodation=True)


def test_trip_profile_validation_days() -> None:
    with pytest.raises(Exception):
        TripProfile.model_validate(
            {
                "days": 0,
                "dietary_choice": "Doesn't matter / no preference",
                "mobility_choice": "No specific needs",
                "include_accommodation": False,
            }
        )


def test_interest_tag_must_be_allowed() -> None:
    valid = list(get_interest_options())[:1]
    if not valid:
        pytest.skip("no interest options loaded")
    TripProfile(
        days=2,
        include_accommodation=True,
        dietary_choice="Doesn't matter / no preference",
        mobility_choice="No specific needs",
        interest_tags=valid,
    )
    with pytest.raises(Exception):
        TripProfile(
            days=2,
            include_accommodation=True,
            dietary_choice="Doesn't matter / no preference",
            mobility_choice="No specific needs",
            interest_tags=["Not a real tag"],
        )


def test_date_range_must_be_ordered() -> None:
    with pytest.raises(Exception):
        TripProfile(
            days=3,
            start_date=date(2026, 5, 5),
            end_date=date(2026, 5, 4),
            include_accommodation=True,
            dietary_choice="Doesn't matter / no preference",
            mobility_choice="No specific needs",
        )
