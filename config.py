"""Runtime configuration for the attendance application.

Set the environment variables in deployment rather than editing this file.
"""
from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


class Config:
    SECRET_KEY = os.environ.get("ATTENDANCE_SECRET_KEY")
    DATABASE = os.environ.get("ATTENDANCE_DATABASE", str(BASE_DIR / "attendance.db"))
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 8
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024
    # Configure this only when the app is actually behind that many trusted proxies.
    TRUSTED_PROXY_COUNT = int(os.environ.get("TRUSTED_PROXY_COUNT", "0"))
    COLLEGE_IP_RANGES = [
        item.strip()
        for item in os.environ.get(
            "COLLEGE_IP_RANGES", "10.27.126.0/24"
        ).split(",")
        if item.strip()
    ]
    SESSION_TTL_SECONDS = int(os.environ.get("SESSION_TTL_SECONDS", "120"))
    GEOFENCE_RADIUS_METERS = float(os.environ.get("GEOFENCE_RADIUS_METERS", "50"))
    SUBJECTS = [
        item.strip()
        for item in os.environ.get("SUBJECTS", "CS101,CS102,MA101,").split(",")
        if item.strip()
    ]
