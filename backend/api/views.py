from rest_framework.decorators import api_view
from rest_framework.response import Response
from .providers import TripError, fetch_trip
from .routing import normalize_routes
from .serializers import TripSerializer
from .weather import enrich_routes
from .ranking import summarize_and_recommend


@api_view(["GET"])
def health(request):
    return Response({"status": "ok", "service": "weather-aware-truck-routing"})


@api_view(["POST"])
def analyze_trip(request):
    serializer = TripSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": {"code": "validation_error", "message": "Check the request fields.", "fields": serializer.errors}}, status=400)
    data = serializer.validated_data
    try:
        locations, raw_routes = fetch_trip(data["origin"], data["destination"], data["departure_time"])
        routes = normalize_routes(raw_routes, data["departure_time"], data["checkpoint_interval_miles"])
        weather_coverage = enrich_routes(routes, data["load_weight_lbs"])
        recommendation = summarize_and_recommend(routes)
    except TripError as exc:
        return Response({"error": {"code": exc.code, "message": exc.message}}, status=exc.status)
    return Response({"origin": locations[0], "destination": locations[1],
                     "departure_time": data["departure_time"].isoformat(),
                     "load_weight_lbs": data["load_weight_lbs"], "weight_semantics": "cargo_only",
                     "checkpoint_interval_miles": data["checkpoint_interval_miles"],
                     "weather_coverage": weather_coverage,
                     "recommended_route_id": recommendation["recommended_route_id"],
                     "recommendation": recommendation,
                     "route_count": len(routes), "routes": routes})
