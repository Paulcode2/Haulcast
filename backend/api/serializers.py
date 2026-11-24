import math
import re
from datetime import datetime

from rest_framework import serializers


class LocationField(serializers.CharField):
    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail("invalid")
        return super().to_internal_value(data)


class DepartureField(serializers.Field):
    def to_internal_value(self, value):
        if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value
        ):
            raise serializers.ValidationError("Use ISO8601 with seconds and an explicit UTC offset, e.g. 2026-11-25T09:00:00+01:00.")
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
            offset = value[-6:]
            if not value.endswith("Z") and (int(offset[1:3]) > 23 or int(offset[4:]) > 59):
                raise ValueError
            return result
        except ValueError:
            raise serializers.ValidationError("Invalid departure date/time or UTC offset.") from None


class CargoWeightField(serializers.FloatField):
    def to_internal_value(self, value):
        if isinstance(value, bool):
            raise serializers.ValidationError("Enter a finite positive cargo weight in pounds.")
        number = super().to_internal_value(value)
        if not math.isfinite(number) or number <= 0:
            raise serializers.ValidationError("Enter a finite positive cargo weight in pounds.")
        return number


class IntervalField(serializers.ChoiceField):
    def to_internal_value(self, value):
        if isinstance(value, bool):
            self.fail("invalid_choice", input=value)
        return super().to_internal_value(value)


class TripSerializer(serializers.Serializer):
    origin = LocationField(max_length=500)
    destination = LocationField(max_length=500)
    departure_time = DepartureField()
    load_weight_lbs = CargoWeightField()
    checkpoint_interval_miles = IntervalField(choices=[10, 25, 50], default=25)
