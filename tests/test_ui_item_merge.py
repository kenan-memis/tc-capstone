from planmyberlin.ui.app import _merge_display_items


def test_merge_display_items_keeps_unenriched_rows() -> None:
    retrieved = [
        {"name": "Museum Island", "category": "places", "district": "Mitte"},
        {"name": "Cafe Engelbecken", "category": "restaurants", "district": "Kreuzberg"},
    ]
    enriched = [
        {"name": "Museum Island", "category": "places", "district": "Mitte", "latitude": 52.5169, "longitude": 13.401}
    ]

    out = _merge_display_items(retrieved, enriched)
    assert len(out) == 2
    assert any(str(x.get("name")) == "Cafe Engelbecken" for x in out)
    assert any(str(x.get("name")) == "Museum Island" and x.get("latitude") is not None for x in out)
