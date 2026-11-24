from django.urls import path
from api.views import health, analyze_trip

urlpatterns = [path("api/health/", health), path("api/trips/analyze", analyze_trip), path("api/trips/analyze/", analyze_trip)]
