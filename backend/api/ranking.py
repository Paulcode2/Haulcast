"""Distance-weighted summaries and lexicographic ranking, without display rounding."""
from math import fsum

from .risk import LEVELS
from .routing import METRES_PER_MILE

RISK_SCALE = dict(zip(LEVELS, range(5)))
CRITERIA = ("severe_miles", "high_miles", "average_risk", "duration_seconds")


def checkpoint_complete(point):
    risk = point.get("risk", {})
    return (risk.get("level") in RISK_SCALE and risk.get("coverage_complete") is True
            and point.get("weather", {}).get("coverage", {}).get("status") == "complete")


def summarize_route(route):
    points = route["checkpoints"]
    segments = []
    for index, (start, end) in enumerate(zip(points, points[1:])):
        # Use unrounded distance along the polyline, not nominal interval or chord.
        length = (end["distance_meters"] - start["distance_meters"]) / METRES_PER_MILE
        if length <= 0:
            raise ValueError("Checkpoint distances must strictly increase.")
        complete = checkpoint_complete(start) and checkpoint_complete(end)
        levels = [point.get("risk", {}).get("level", "Unknown") for point in (start, end)]
        if "No Travel" in levels:
            level = "No Travel"  # A known maximum survives missing weather at either end.
        elif complete:
            level = max(levels, key=RISK_SCALE.__getitem__)
        else:
            level = "Unknown"
        segments.append({"index": index, "start_checkpoint_index": start["index"],
                         "end_checkpoint_index": end["index"], "distance_miles": length,
                         "risk_level": level, "forecast_coverage_complete": complete})
    miles = {level: fsum(s["distance_miles"] for s in segments if s["risk_level"] == level)
             for level in (*LEVELS, "Unknown")}
    total = fsum(s["distance_miles"] for s in segments)
    unknown_coverage = fsum(s["distance_miles"] for s in segments if not s["forecast_coverage_complete"])
    complete = bool(segments) and all(checkpoint_complete(p) for p in points)
    average = (fsum(s["distance_miles"] * RISK_SCALE[s["risk_level"]] for s in segments) / total
               if total and not miles["Unknown"] else None)
    reasons = []
    if miles["No Travel"] > 0:
        reasons.append({"code": "no_travel_segments", "message": "Route contains confirmed No Travel segments."})
    if not complete:
        reasons.append({"code": "incomplete_forecast_coverage", "message": "One or more checkpoints lack complete forecast coverage; this route cannot be recommended."})
    summary = {"distance_miles": total, "severe_miles": miles["Severe"], "high_miles": miles["High"],
               "no_travel_miles": miles["No Travel"], "unknown_coverage_miles": unknown_coverage,
               "unknown_risk_miles": miles["Unknown"], "average_risk": average,
               "forecast_coverage_complete": complete, "eligible": not reasons, "exclusion_reasons": reasons}
    summary["display"] = {key: round(value, 2) if value is not None else None
                          for key, value in summary.items() if key.endswith("_miles") or key == "average_risk"}
    return summary, segments


def summarize_and_recommend(routes):
    eligible = []
    for route in routes:
        route["summary"], route["segments"] = summarize_route(route)
        if route["summary"]["eligible"]:
            eligible.append(route)

    def key(route):
        summary = route["summary"]
        return (summary["severe_miles"], summary["high_miles"], summary["average_risk"], route["duration_seconds"])

    eligible.sort(key=key)  # Stable on exact ties: retain provider order.
    if not eligible:
        return {"recommended_route_id": None, "status": "no_recommendation", "deciding_factor": None,
                "explanation": "No route has both complete forecast coverage and no No Travel segments."}
    winner = eligible[0]
    if len(eligible) == 1:
        factor, explanation = "only_eligible_route", "Only this route has complete forecast coverage and no No Travel segments."
    else:
        runner_up = eligible[1]
        factor = next((name for name, a, b in zip(CRITERIA, key(winner), key(runner_up)) if a != b), "exact_tie")
        explanations = {
            "severe_miles": "Fewest Severe miles decides the comparison with the next-ranked eligible route.",
            "high_miles": "Severe miles tie; fewer High miles decides the comparison with the next-ranked eligible route.",
            "average_risk": "Severe and High miles tie; lower distance-weighted average risk decides the comparison with the next-ranked eligible route.",
            "duration_seconds": "All risk metrics tie; shorter travel time decides the comparison with the next-ranked eligible route.",
            "exact_tie": "All four criteria tie exactly; the first eligible route in provider order is retained.",
        }
        explanation = explanations[factor]
    return {"recommended_route_id": winner["id"], "status": "recommended", "deciding_factor": factor,
            "explanation": explanation}
