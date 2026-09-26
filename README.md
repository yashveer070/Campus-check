# CampusCheck — WiFi-validated QR attendance

A Flask + SQLite attendance system for short-lived classroom QR codes. It records attendance only after all server-side checks pass:

- authenticated student account;
- configured college CIDR range;
- valid, active 60-second session;
- 100 m Haversine GPS geofence;
- one check-in per student and session;
- duplicate device-fingerprint flagging; and
- immutable-style audit events with client IP logging.

The student scanner uses qr-scanner.js from jsDelivr, requests high-accuracy geolocation, and stores a small pending check-in queue in browser local storage when the network drops. A queued check-in is still revalidated by the server when it syncs and will fail safely if the QR has expired.

## Run locally

From this folder:

    py -m venv .venv
    .\.venv\Scripts\Activate.ps1
    pip install -r requirements.txt
    $env:ATTENDANCE_SECRET_KEY = python -c "import secrets; print(secrets.token_urlsafe(48))"
    python app.py

Open http://127.0.0.1:5000. The database is initialized automatically; use the commands below to add accounts:

    $env:FLASK_APP = "app:create_app"
    flask create-teacher --id T001 --name "Dr Rao" --email rao@example.edu --department CSE
    flask create-student --id S001 --name "Asha Singh" --roll-number 2026CSE001 --semester 1 --department CSE

Teacher accounts use a Werkzeug password hash. In line with the brief's “simple password or roll number” requirement, the student’s roll number is their sign-in credential. For a real college deployment, replace it with a student password/SSO flow before launch.

## Deployment configuration

Copy the values in .env.example into your deployment’s secret manager or environment. Set:

- ATTENDANCE_SECRET_KEY to a strong, unique random value;
- SESSION_COOKIE_SECURE=true behind HTTPS;
- COLLEGE_IP_RANGES to the actual egress CIDRs of the college WiFi; and
- TRUSTED_PROXY_COUNT only when that many trusted reverse proxies are in front of the application.

Never trust a user-supplied X-Forwarded-For header directly. The application uses Werkzeug ProxyFix only for the configured proxy count, then validates request.remote_addr.

The default ranges intentionally reject 127.0.0.1, so a local student check-in will fail the WiFi gate unless you temporarily configure COLLEGE_IP_RANGES=127.0.0.0/8 for development. This should never be used in production.

## Limits worth knowing

The supplied schema does not include course enrollment, so “not recorded” counts use all provisioned students, and the student history labels unrecorded sessions explicitly rather than asserting formal absences. Add an enrollment table before using attendance percentages as an official academic record.

The optional admin import/user-management modules were not added because the provided schema has no admin identity/authorization model. Add a distinct admin role and approval policy before enabling bulk account changes.
