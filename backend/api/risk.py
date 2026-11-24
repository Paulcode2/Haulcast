"""Pure assessment rules. Inputs are mph, inches/hour, and cargo pounds."""
import math

LEVELS = ("Low", "Moderate", "High", "Severe", "No Travel")


def valid_value(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def classify_risk(wind_mph, rain_in_per_hour, snow_in_per_hour, load_weight_lbs):
    if not valid_value(load_weight_lbs) or load_weight_lbs <= 0:
        raise ValueError("Cargo weight must be finite and positive.")
    conditions = []
    missing = []
    for field, value in (("wind_mph", wind_mph), ("rain_in_per_hour", rain_in_per_hour), ("snow_in_per_hour", snow_in_per_hour)):
        if not valid_value(value):
            missing.append(field)
            continue
        if field == "wind_mph":
            rank = sum(value >= boundary for boundary in (25, 35, 45, 55))
            reason = f"Wind {value:g} mph: {LEVELS[rank]}."
            if 45 <= value < 55 and load_weight_lbs > 30000:
                rank = 4
                reason = "Wind 45–<55 mph with cargo above 30,000 lb: No Travel."
            elif 35 <= value < 45 and load_weight_lbs > 40000:
                rank = 3
                reason = "Wind 35–<45 mph with cargo above 40,000 lb: Severe."
        else:
            boundaries = (0.10, 0.25, 0.50, 1.00) if field == "rain_in_per_hour" else (0.5, 1.0, 2.0, 3.0)
            rank = sum(value >= boundary for boundary in boundaries[:3]) + (value > boundaries[3])
            label = "Rain" if field == "rain_in_per_hour" else "Snow"
            reason = f"{label} {value:g} in/hr: {LEVELS[rank]}."
        conditions.append((rank, field, reason))
    highest = max((c[0] for c in conditions), default=None)
    return {"level": LEVELS[highest] if highest is not None else "Unknown",
            "reasons": [c[2] for c in conditions if c[0] == highest] or ["No usable weather data for this ETA."],
            "triggering_conditions": [c[1] for c in conditions if c[0] == highest],
            "coverage_complete": not missing, "missing_fields": missing,
            "assessment_status": "confirmed" if not missing or highest == 4 else "incomplete"}
