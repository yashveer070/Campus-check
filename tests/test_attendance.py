from datetime import timedelta

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from database import get_db
from services import calculate_distance, to_iso, utcnow


@pytest.fixture()
def app(tmp_path):
    application = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "test.db"),
        "COLLEGE_IP_RANGES": ["127.0.0.0/8"],
        "SUBJECTS": ["CS101"],
        "SESSION_TTL_SECONDS": 60,
    })
    with application.app_context():
        db = get_db()
        db.execute(
            "INSERT INTO teachers (teacher_id, name, email, password_hash) VALUES (?, ?, ?, ?)",
            ("T001", "Teacher", "teacher@example.edu", generate_password_hash("safe-password")),
        )
        db.execute(
            "INSERT INTO students (student_id, name, roll_number) VALUES (?, ?, ?)",
            ("S001", "Student One", "ROLL001"),
        )
        db.execute(
            "INSERT INTO students (student_id, name, roll_number) VALUES (?, ?, ?)",
            ("S002", "Student Two", "ROLL002"),
        )
    return application


def set_identity(client, user_id, role):
    with client.session_transaction() as browser_session:
        browser_session["user_id"] = user_id
        browser_session["role"] = role
        browser_session["csrf_token"] = "csrf-test"


def csrf_json(payload):
    return {"json": payload, "headers": {"X-CSRF-Token": "csrf-test"}, "environ_base": {"REMOTE_ADDR": "127.0.0.1"}}


def create_session(client):
    set_identity(client, "T001", "teacher")
    response = client.post("/api/teacher/sessions", **csrf_json({
        "subject_code": "CS101", "latitude": 12.9716, "longitude": 77.5946,
    }))
    assert response.status_code == 201
    return response.get_json()["session_token"]


def test_marks_attendance_only_once_when_network_and_geofence_are_valid(app):
    client = app.test_client()
    token = create_session(client)
    set_identity(client, "S001", "student")
    payload = {"session_token": token, "latitude": 12.97161, "longitude": 77.59461, "accuracy": 5, "device_fingerprint": "device-a"}

    assert client.post("/api/mark-attendance", **csrf_json(payload)).status_code == 201
    duplicate = client.post("/api/mark-attendance", **csrf_json(payload))
    assert duplicate.status_code == 409


def test_rejects_student_outside_geofence(app):
    client = app.test_client()
    token = create_session(client)
    set_identity(client, "S001", "student")
    response = client.post("/api/mark-attendance", **csrf_json({
        "session_token": token, "latitude": 12.9816, "longitude": 77.5946, "accuracy": 5, "device_fingerprint": "device-a",
    }))
    assert response.status_code == 403
    assert "outside" in response.get_json()["error"]


def test_haversine_distance_uses_the_earth_radius():
    # One degree of longitude at the equator is roughly 111 km, not a few metres.
    assert calculate_distance(0, 0, 0, 1) == pytest.approx(111.2, rel=0.01)


def test_qr_url_uses_forwarded_https_origin(app):
    app.config["TRUSTED_PROXY_COUNT"] = 1
    # Recreate the app so ProxyFix reads the changed setting before wrapping WSGI.
    proxied_app = create_app({
        "TESTING": True,
        "DATABASE": app.config["DATABASE"],
        "SECRET_KEY": app.config["SECRET_KEY"],
        "COLLEGE_IP_RANGES": ["127.0.0.0/8"],
        "SUBJECTS": ["CS101"],
        "TRUSTED_PROXY_COUNT": 1,
    })
    client = proxied_app.test_client()
    set_identity(client, "T001", "teacher")
    response = client.post(
        "/api/teacher/sessions",
        json={"subject_code": "CS101", "latitude": 12.9716, "longitude": 77.5946},
        headers={
            "X-CSRF-Token": "csrf-test",
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "attendance.example.edu",
        },
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert response.status_code == 201
    assert response.get_json()["scan_url"].startswith("https://attendance.example.edu/student/scan?")


def test_expired_or_unknown_token_is_rejected_and_audited_safely(app):
    client = app.test_client()
    token = create_session(client)
    with app.app_context():
        get_db().execute("UPDATE sessions SET expires_at = ? WHERE session_token = ?", (to_iso(utcnow() - timedelta(seconds=1)), token))
    set_identity(client, "S001", "student")
    expired = client.post("/api/mark-attendance", **csrf_json({
        "session_token": token, "latitude": 12.9716, "longitude": 77.5946, "accuracy": 5, "device_fingerprint": "device-a",
    }))
    assert expired.status_code == 410
    unknown = client.post("/api/mark-attendance", **csrf_json({
        "session_token": "nonexistent-token-12345", "latitude": 12.9716, "longitude": 77.5946, "accuracy": 5, "device_fingerprint": "device-a",
    }))
    assert unknown.status_code == 404


def test_same_device_for_another_student_is_flagged(app):
    client = app.test_client()
    token = create_session(client)
    base = {"session_token": token, "latitude": 12.9716, "longitude": 77.5946, "accuracy": 5, "device_fingerprint": "shared-device"}
    set_identity(client, "S001", "student")
    assert client.post("/api/mark-attendance", **csrf_json(base)).status_code == 201
    set_identity(client, "S002", "student")
    response = client.post("/api/mark-attendance", **csrf_json(base))
    assert response.status_code == 201
    assert response.get_json()["flagged"] is True
