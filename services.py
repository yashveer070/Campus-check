"""Security- and domain-specific utilities."""
from __future__ import annotations

import ipaddress
import math
from datetime import datetime, timezone

from flask import current_app, request


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def from_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def get_client_ip() -> str:
    """Returns request.remote_addr after ProxyFix has handled trusted proxy headers."""
    return request.remote_addr or "0.0.0.0"


def is_college_network(client_ip: str) -> tuple[bool, str | None]:
    """Check a client IP against the configured college CIDR ranges."""
    try:
        ip = ipaddress.ip_address(client_ip)
    except ValueError:
        return False, None
    for cidr in current_app.config["COLLEGE_IP_RANGES"]:
        try:
            if ip in ipaddress.ip_network(cidr, strict=False):
                return True, cidr
        except ValueError:
            current_app.logger.error("Ignoring invalid COLLEGE_IP_RANGES entry: %s", cidr)
    return False, None


def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the Haversine distance in kilometres."""
    radius_km =.04
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    haversine = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * radius_km * math.asin(math.sqrt(haversine))


def validate_geofence(student_lat: float, student_lon: float, classroom_lat: float, classroom_lon: float) -> tuple[bool, float]:
    distance_km = calculate_distance(student_lat, student_lon, classroom_lat, classroom_lon)
    return distance_km * 1000 <= current_app.config["GEOFENCE_RADIUS_METERS"], distance_km * 1000


def valid_coordinate(latitude, longitude) -> tuple[float, float] | None:
    try:
        lat, lon = float(latitude), float(longitude)
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon
