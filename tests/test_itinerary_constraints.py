from planmyberlin.itinerary.constraints import enforce_day_count, format_constraint_instructions, strip_itinerary_timing
from planmyberlin.itinerary.models import ItineraryActivity, ItineraryDay, TripItinerary


def test_enforce_day_count_pads() -> None:
    it = TripItinerary(
        title="T",
        days=[
            ItineraryDay(
                day_number=1,
                theme="One",
                activities=[
                    ItineraryActivity(
                        time_of_day="morning",
                        title="A",
                        description="d",
                        place_name=None,
                    )
                ],
            )
        ],
        practical_notes=[],
    )
    fixed, changed = enforce_day_count(it, 3)
    assert changed is True
    assert len(fixed.days) == 3
    assert fixed.days[-1].day_number == 3


def test_strip_timing() -> None:
    it = TripItinerary(
        title="Plan at 10:30",
        days=[
            ItineraryDay(
                day_number=1,
                theme="Day",
                activities=[
                    ItineraryActivity(
                        time_of_day="morning",
                        title="Meet at 09:15",
                        description="Coffee",
                        place_name=None,
                    )
                ],
            )
        ],
        practical_notes=[],
    )
    out = strip_itinerary_timing(it)
    assert "10:30" not in out.title
    assert "09:15" not in out.days[0].activities[0].title


def test_format_constraint_instructions_includes_days() -> None:
    text = format_constraint_instructions({"days": 4, "pace": "relaxed", "dietary_choice": "x", "mobility_choice": "y"})
    assert "4" in text
    assert "relaxed" in text.lower()
