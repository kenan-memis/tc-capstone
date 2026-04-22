"""CLI to expand seed YAML knowledge base using Google Places."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import planmyberlin.env  # noqa: F401 - load .env for local usage

from planmyberlin.config.loader import get_neighbourhood_options
from planmyberlin.kb import DEFAULT_DISTRICT_PLAN, build_seed_for_district


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Expand raw seed KB from Google Places")
    parser.add_argument(
        "--district",
        action="append",
        default=[],
        help="District name to ingest (repeat for multiple). Defaults to built-in plan if omitted.",
    )
    parser.add_argument("--city", default="Berlin")
    parser.add_argument("--output-root", default="data/raw")
    parser.add_argument("--timeout-seconds", type=float, default=12.0)
    parser.add_argument(
        "--restaurants-target",
        type=int,
        default=0,
        help="Override restaurant target for all districts (0 => per-district plan).",
    )
    parser.add_argument(
        "--places-target",
        type=int,
        default=0,
        help="Override places target for all districts (0 => per-district plan).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    api_key = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("GOOGLE_PLACES_API_KEY is required to build seed KB")

    if args.district:
        district_plan = {
            d: {
                "restaurants": args.restaurants_target or 50,
                "places": args.places_target or 15,
            }
            for d in args.district
        }
    else:
        # Cover every selectable UI area with a baseline quota.
        base_restaurants = args.restaurants_target or 5
        base_places = args.places_target or 3
        district_plan = {
            area: {"restaurants": base_restaurants, "places": base_places}
            for area in get_neighbourhood_options()
        }
        # Keep higher quotas for core areas from the predefined plan.
        for area, quotas in DEFAULT_DISTRICT_PLAN.items():
            if area not in district_plan:
                district_plan[area] = dict(quotas)
                continue
            district_plan[area]["restaurants"] = max(
                int(district_plan[area]["restaurants"]),
                int(quotas.get("restaurants", base_restaurants)),
            )
            district_plan[area]["places"] = max(
                int(district_plan[area]["places"]),
                int(quotas.get("places", base_places)),
            )

    out_root = Path(args.output_root)

    print(f"Building KB for {len(district_plan)} districts into: {out_root}")
    for district, quotas in district_plan.items():
        res = build_seed_for_district(
            district=district,
            city=args.city,
            api_key=api_key,
            output_root=out_root,
            restaurants_target=int(quotas.get("restaurants", 30)),
            places_target=int(quotas.get("places", 10)),
            timeout_seconds=float(args.timeout_seconds),
        )
        print(
            f"[{res.district}] places={res.places_total} (+{res.places_added}), "
            f"restaurants={res.restaurants_total} (+{res.restaurants_added})"
        )


if __name__ == "__main__":
    main()
