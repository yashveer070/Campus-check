# CampusCheck — location-validated QR attendance

A Flask + SQLite attendance system for short-lived classroom QR codes. Attendance is recorded only after these server-side checks pass:

- authenticated student account;
- valid, active QR session;
- required precise GPS reading (50 m accuracy or better by default);
- configurable classroom geofence (50 m by default);
- one check-in per student and session; and
- duplicate device-fingerprint flagging.

There is no Wi-Fi, IP-range, or campus-network eligibility check. A student can check in from any connection, including mobile data, as long as their device has Internet access, the QR session is active, and their precise location is inside the classroom boundary.

The student scanner uses qr-scanner.js from jsDelivr, requests high-accuracy geolocation, and stores a small pending check-in queue in browser local storage when the connection drops. A queued check-in is still revalidated by the server when it syncs and will fail safely if the QR has expired or its location no longer qualifies.

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

Teacher accounts use a Werkzeug password hash. In line with the brief's “simple password or roll number” requirement, the student's roll number is their sign-in credential. For a real college deployment, replace it with a student password or SSO flow before launch.

## Deployment configuration

Copy the values in .env.example into the deployment's secret manager or environment. Set:

- ATTENDANCE_SECRET_KEY to a strong, unique random value;
- SESSION_COOKIE_SECURE=true behind HTTPS;
- GEOFENCE_RADIUS_METERS to the size of the classroom boundary;
- MAX_LOCATION_ACCURACY_METERS to the least precise GPS reading you will accept; and
- TRUSTED_PROXY_COUNT only when that many trusted reverse proxies are in front of the application.

The default accuracy and geofence limits are both 50 m. A public deployment must use HTTPS so phone browsers can access the camera and location services.

## Internet deployment

The app includes a production WSGI entry point and Dockerfile. Use exactly one application worker with SQLite and mount a persistent volume at /data; set ATTENDANCE_DATABASE=/data/attendance.db on a non-Docker host.

Set TRUSTED_PROXY_COUNT=1 only when the app is behind one proxy you control. This preserves the public HTTPS URL in generated QR codes; it does not affect attendance eligibility.

For a permanent public address, run the Docker image on a host with persistent storage or configure a named tunnel with a domain you control. A temporary Quick Tunnel is suitable for testing only.

## Limits worth knowing

The supplied schema does not include course enrollment, so “not recorded” counts use all provisioned students, and the student history labels unrecorded sessions explicitly rather than asserting formal absences. Add an enrollment table before using attendance percentages as an official academic record.

The optional admin import and user-management modules were not added because the provided schema has no admin identity or authorization model. Add a distinct admin role and approval policy before enabling bulk account changes.
