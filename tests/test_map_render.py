from planmyberlin.map.render import build_preview_map


def test_build_preview_map_with_points() -> None:
    points = [
        {
            "name": "Museum Island",
            "category": "places",
            "district": "Mitte",
            "summary": "UNESCO museum complex",
            "latitude": 52.5169,
            "longitude": 13.4010,
        },
        {
            "name": "Markthalle Neun",
            "category": "restaurants",
            "district": "Kreuzberg",
            "summary": "Food hall",
            "latitude": 52.5037,
            "longitude": 13.4317,
        },
    ]

    m = build_preview_map(points)
    html = m.get_root().render()
    assert "Museum Island" in html
    assert "Markthalle Neun" in html


def test_build_preview_map_without_coordinates() -> None:
    points = [{"name": "No coords", "category": "places", "district": "Mitte", "summary": "x"}]
    m = build_preview_map(points)
    html = m.get_root().render()
    assert "No coords" not in html
