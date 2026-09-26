"""WiFi-validated QR attendance application."""
from __future__ import annotations

import base64
import csv
import io
import json
import os
import secrets
import sqlite3
from datetime import timedelta
from functools import wraps

import click
import qrcode
from flask import Flask, Response, abort, flash, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

from config import Config
from database import close_db, get_db, init_db, log_event
from services import from_iso, get_client_ip, is_college_network, to_iso, utcnow, valid_coordinate, validate_geofence


def create_app(test_config=None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    if not app.config["SECRET_KEY"]:
        if app.config.get("TESTING"):
            app.config["SECRET_KEY"] = "test-only-secret"
        else:
            raise RuntimeError("Set ATTENDANCE_SECRET_KEY to a long random value before starting the app.")

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=app.config["TRUSTED_PROXY_COUNT"])
    app.teardown_appcontext(close_db)

    @app.before_request
    def load_principal_and_protect_csrf():
        g.user_id = session.get("user_id")
        g.role = session.get("role")
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            supplied = request.headers.get("X-CSRF-Token") if request.is_json else request.form.get("csrf_token")
            if not supplied or not secrets.compare_digest(supplied, session["csrf_token"]):
                if request.is_json:
                    return jsonify(error="Invalid or missing CSRF token."), 400
                abort(400, "Invalid or missing CSRF token.")

    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(self), geolocation=(self)"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; worker-src 'self' blob: https://cdn.jsdelivr.net"
        )
        return response

    def role_required(role: str):
        def decorator(view):
            @wraps(view)
            def wrapped(*args, **kwargs):
                if g.role != role:
                    flash("Please sign in with the required account.", "error")
                    return redirect(url_for("login", role=role))
                return view(*args, **kwargs)
            return wrapped
        return decorator

    def api_role_required(role: str):
        def decorator(view):
            @wraps(view)
            def wrapped(*args, **kwargs):
                if g.role != role:
                    return jsonify(error="Authentication required."), 401
                return view(*args, **kwargs)
            return wrapped
        return decorator

    def owner_session_or_404(session_token: str):
        record = get_db().execute(
            "SELECT * FROM sessions WHERE session_token = ? AND teacher_id = ?",
            (session_token, g.user_id),
        ).fetchone()
        if record is None:
            abort(404)
        return record

    @app.context_processor
    def template_values():
        return {"csrf_token": session.get("csrf_token", ""), "subjects": app.config["SUBJECTS"]}

    @app.get("/")
    def index():
        if g.role == "teacher":
            return redirect(url_for("teacher_generate_qr"))
        if g.role == "student":
            return redirect(url_for("student_scan"))
        return render_template("index.html")

    @app.route("/login/<role>", methods=["GET", "POST"])
    def login(role: str):
        if role not in {"teacher", "student"}:
            abort(404)
        if request.method == "POST":
            identifier = request.form.get("identifier", "").strip()
            password = request.form.get("password", "")
            db = get_db()
            if role == "teacher":
                account = db.execute(
                    "SELECT teacher_id AS id, password_hash FROM teachers WHERE email = ?", (identifier.lower(),)
                ).fetchone()
                valid = bool(account and check_password_hash(account["password_hash"], password))
            else:
                account = db.execute(
                    "SELECT student_id AS id, roll_number FROM students WHERE student_id = ?", (identifier,)
                ).fetchone()
                # Student roll number is the deliberately simple credential requested in the brief.
                valid = bool(account and secrets.compare_digest(account["roll_number"], password))
            if valid:
                session.clear()
                session["user_id"] = account["id"]
                session["role"] = role
                session["csrf_token"] = secrets.token_urlsafe(32)
                session.permanent = True
                log_event("login", student_id=account["id"] if role == "student" else None, client_ip=get_client_ip(), details=json.dumps({"role": role}))
                return redirect(url_for("teacher_generate_qr" if role == "teacher" else "student_scan"))
            flash("Incorrect sign-in details.", "error")
        return render_template("login.html", role=role)

    @app.post("/logout")
    def logout():
        session.clear()
        flash("You have been signed out.", "success")
        return redirect(url_for("index"))

    @app.get("/teacher/generate-qr")
    @role_required("teacher")
    def teacher_generate_qr():
        return render_template("teacher_generate.html")

    @app.post("/api/teacher/sessions")
    @api_role_required("teacher")
    def create_session():
        data = request.get_json(silent=True) or {}
        subject = str(data.get("subject_code", "")).strip().upper()
        coords = valid_coordinate(data.get("latitude"), data.get("longitude"))
        if subject not in app.config["SUBJECTS"] or not coords:
            return jsonify(error="Choose a configured subject and a valid classroom location."), 400
        now = utcnow()
        expires = now + timedelta(seconds=app.config["SESSION_TTL_SECONDS"])
        token = secrets.token_urlsafe(24)
        db = get_db()
        db.execute(
            """INSERT INTO sessions (session_token, teacher_id, subject_code, classroom_lat, classroom_lon, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (token, g.user_id, subject, coords[0], coords[1], to_iso(now), to_iso(expires)),
        )
        target = url_for("student_scan", token=token, _external=True)
        image = qrcode.make(target)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        encoded_qr = base64.b64encode(buffer.getvalue()).decode("ascii")
        log_event("session_created", session_token=token, client_ip=get_client_ip(), details=json.dumps({"subject": subject}))
        return jsonify(
            session_token=token,
            subject_code=subject,
            expires_at=to_iso(expires),
            scan_url=target,
            qr_data_url=f"data:image/png;base64,{encoded_qr}",
            dashboard_url=url_for("teacher_dashboard", session_token=token),
        ), 201

    @app.get("/teacher/dashboard/<session_token>")
    @role_required("teacher")
    def teacher_dashboard(session_token: str):
        record = owner_session_or_404(session_token)
        return render_template("teacher_dashboard.html", class_session=record)

    @app.get("/api/teacher/dashboard/<session_token>")
    @api_role_required("teacher")
    def teacher_dashboard_data(session_token: str):
        class_session = owner_session_or_404(session_token)
        db = get_db()
        rows = db.execute(
            """SELECT a.*, s.name, s.roll_number FROM attendance a
               JOIN students s ON s.student_id = a.student_id
               WHERE a.session_token = ? ORDER BY a.timestamp ASC""",
            (session_token,),
        ).fetchall()
        total_students = db.execute("SELECT COUNT(*) FROM students").fetchone()[0]
        present = len(rows)
        return jsonify(
            session={"subject_code": class_session["subject_code"], "expires_at": class_session["expires_at"]},
            attendance=[dict(row) for row in rows],
            stats={
                "present": present,
                "total_students": total_students,
                "absent": max(total_students - present, 0),
                "percentage": round((present / total_students * 100) if total_students else 0, 1),
            },
        )

    @app.post("/api/teacher/dashboard/<session_token>/manual-attendance")
    @api_role_required("teacher")
    def manual_attendance(session_token: str):
        owner_session_or_404(session_token)
        data = request.get_json(silent=True) or {}
        student_id = str(data.get("student_id", "")).strip()
        db = get_db()
        if not db.execute("SELECT 1 FROM students WHERE student_id = ?", (student_id,)).fetchone():
            return jsonify(error="Unknown student ID."), 404
        try:
            db.execute(
                """INSERT INTO attendance (session_token, student_id, timestamp, client_ip, network_range, device_fingerprint)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (session_token, student_id, to_iso(utcnow()), get_client_ip(), "manual", f"manual:{g.user_id}"),
            )
        except sqlite3.IntegrityError:
            return jsonify(error="This student is already recorded for the session."), 409
        log_event("manual_attendance", session_token=session_token, student_id=student_id, client_ip=get_client_ip())
        return jsonify(message="Manual attendance recorded."), 201

    @app.get("/teacher/dashboard/<session_token>/export.csv")
    @role_required("teacher")
    def export_session_csv(session_token: str):
        owner_session_or_404(session_token)
        rows = get_db().execute(
            """SELECT s.roll_number, s.name, a.timestamp, a.client_ip, a.latitude, a.longitude,
                      a.accuracy, a.network_range, a.is_flagged, a.flag_reason
               FROM attendance a JOIN students s ON s.student_id = a.student_id
               WHERE a.session_token = ? ORDER BY a.timestamp""", (session_token,),
        ).fetchall()
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["Roll Number", "Name", "Time (UTC)", "IP Address", "Latitude", "Longitude", "Accuracy (m)", "Network Range", "Flagged", "Flag Reason"])
        writer.writerows([tuple(row) for row in rows])
        return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename=attendance-{session_token[:8]}.csv"})

    @app.get("/teacher/history")
    @role_required("teacher")
    def teacher_history():
        start = request.args.get("start", "").strip()
        end = request.args.get("end", "").strip()
        query = """SELECT se.*, COUNT(a.id) AS present_count FROM sessions se
                   LEFT JOIN attendance a ON a.session_token = se.session_token
                   WHERE se.teacher_id = ?"""
        params = [g.user_id]
        if start:
            query += " AND date(se.created_at) >= date(?)"
            params.append(start)
        if end:
            query += " AND date(se.created_at) <= date(?)"
            params.append(end)
        query += " GROUP BY se.session_token ORDER BY se.created_at DESC"
        records = get_db().execute(query, params).fetchall()
        return render_template("teacher_history.html", records=records, start=start, end=end)

    @app.get("/teacher/history/export.csv")
    @role_required("teacher")
    def export_monthly_csv():
        month = request.args.get("month", "").strip()
        query = """SELECT se.subject_code, se.created_at, se.expires_at, COUNT(a.id) AS present_count
                   FROM sessions se LEFT JOIN attendance a ON a.session_token = se.session_token
                   WHERE se.teacher_id = ?"""
        params = [g.user_id]
        if month:
            query += " AND substr(se.created_at, 1, 7) = ?"
            params.append(month)
        query += " GROUP BY se.session_token ORDER BY se.created_at"
        rows = get_db().execute(query, params).fetchall()
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["Subject", "Session Created (UTC)", "Expired (UTC)", "Present Count"])
        writer.writerows([tuple(row) for row in rows])
        suffix = month or "all"
        return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename=attendance-report-{suffix}.csv"})

    @app.get("/student/scan")
    @role_required("student")
    def student_scan():
        return render_template("student_scan.html", initial_token=request.args.get("token", ""))

    @app.get("/api/network-status")
    @api_role_required("student")
    def network_status():
        ip = get_client_ip()
        allowed, matched_range = is_college_network(ip)
        return jsonify(on_college_network=allowed, network_range=matched_range)

    @app.post("/api/mark-attendance")
    @api_role_required("student")
    def mark_attendance():
        data = request.get_json(silent=True) or {}
        token = str(data.get("session_token", "")).strip()
        coords = valid_coordinate(data.get("latitude"), data.get("longitude"))
        fingerprint = str(data.get("device_fingerprint", "")).strip()
        try:
            accuracy = float(data.get("accuracy"))
        except (TypeError, ValueError):
            accuracy = None
        if not token or not coords or not fingerprint or len(fingerprint) > 128:
            return jsonify(error="A session token, valid location, and device fingerprint are required."), 400
        if accuracy is not None and (accuracy < 0 or accuracy > 10_000):
            return jsonify(error="Invalid location accuracy."), 400

        client_ip = get_client_ip()
        on_network, network_range = is_college_network(client_ip)
        if not on_network:
            # The requested token may not exist, while audit_logs deliberately has a
            # foreign key to sessions. Keep the request token only in audit details.
            log_event("attendance_rejected_network", student_id=g.user_id, client_ip=client_ip, details=json.dumps({"requested_token": token[:12]}))
            return jsonify(error="Attendance is available only from a configured college WiFi network."), 403

        db = get_db()
        db.execute("BEGIN IMMEDIATE")
        try:
            class_session = db.execute("SELECT * FROM sessions WHERE session_token = ?", (token,)).fetchone()
            if class_session is None:
                log_event("attendance_rejected_invalid_session", student_id=g.user_id, client_ip=client_ip, details=json.dumps({"requested_token": token[:12]}))
                db.execute("COMMIT")
                return jsonify(error="This QR code is not valid."), 404
            if not class_session["is_active"] or from_iso(class_session["expires_at"]) <= utcnow():
                db.execute("UPDATE sessions SET is_active = 0 WHERE session_token = ?", (token,))
                log_event("attendance_rejected_expired", session_token=token, student_id=g.user_id, client_ip=client_ip)
                db.execute("COMMIT")
                return jsonify(error="This QR code has expired. Ask your teacher for a new code."), 410
            allowed, distance_m = validate_geofence(coords[0], coords[1], class_session["classroom_lat"], class_session["classroom_lon"])
            if not allowed:
                log_event("attendance_rejected_geofence", session_token=token, student_id=g.user_id, client_ip=client_ip, details=json.dumps({"distance_m": round(distance_m, 2)}))
                db.execute("COMMIT")
                return jsonify(error="Your location is outside the 100 m classroom boundary."), 403
            duplicate = db.execute("SELECT 1 FROM attendance WHERE session_token = ? AND student_id = ?", (token, g.user_id)).fetchone()
            if duplicate:
                log_event("attendance_rejected_duplicate", session_token=token, student_id=g.user_id, client_ip=client_ip)
                db.execute("COMMIT")
                return jsonify(error="You have already marked attendance for this session."), 409
            device_owner = db.execute(
                "SELECT student_id FROM attendance WHERE session_token = ? AND device_fingerprint = ? LIMIT 1", (token, fingerprint)
            ).fetchone()
            flagged = bool(device_owner and device_owner["student_id"] != g.user_id)
            reason = "Device fingerprint already used by a different student in this session." if flagged else None
            db.execute(
                """INSERT INTO attendance (session_token, student_id, timestamp, client_ip, latitude, longitude, accuracy, network_range, device_fingerprint, is_flagged, flag_reason)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (token, g.user_id, to_iso(utcnow()), client_ip, coords[0], coords[1], accuracy, network_range, fingerprint, int(flagged), reason),
            )
            log_event("attendance_marked_flagged" if flagged else "attendance_marked", session_token=token, student_id=g.user_id, client_ip=client_ip, details=json.dumps({"distance_m": round(distance_m, 2), "flagged": flagged}))
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        return jsonify(message="Attendance marked successfully.", flagged=flagged, distance_m=round(distance_m, 1)), 201

    @app.get("/student/history")
    @role_required("student")
    def student_history():
        db = get_db()
        records = db.execute(
            """SELECT a.*, se.subject_code FROM attendance a JOIN sessions se ON se.session_token = a.session_token
               WHERE a.student_id = ? ORDER BY a.timestamp DESC""", (g.user_id,),
        ).fetchall()
        subject_rows = db.execute(
            """SELECT se.subject_code, COUNT(se.session_token) AS sessions_held,
                      SUM(CASE WHEN a.student_id IS NOT NULL THEN 1 ELSE 0 END) AS attended
               FROM sessions se LEFT JOIN attendance a ON a.session_token = se.session_token AND a.student_id = ?
               GROUP BY se.subject_code ORDER BY se.subject_code""", (g.user_id,),
        ).fetchall()
        missed = db.execute(
            """SELECT se.subject_code, se.created_at FROM sessions se
               WHERE NOT EXISTS (SELECT 1 FROM attendance a WHERE a.session_token = se.session_token AND a.student_id = ?)
               ORDER BY se.created_at DESC""", (g.user_id,),
        ).fetchall()
        return render_template("student_history.html", records=records, subject_rows=subject_rows, missed=missed)

    @app.cli.command("init-db")
    def init_db_command():
        """Create the SQLite schema."""
        init_db()
        click.echo("Database initialized.")

    @app.cli.command("create-teacher")
    @click.option("--id", "teacher_id", prompt=True)
    @click.option("--name", prompt=True)
    @click.option("--email", prompt=True)
    @click.option("--department", default="")
    @click.password_option()
    def create_teacher(teacher_id, name, email, department, password):
        """Provision a teacher without keeping credentials in source control."""
        init_db()
        try:
            get_db().execute(
                "INSERT INTO teachers (teacher_id, name, email, password_hash, department) VALUES (?, ?, ?, ?, ?)",
                (teacher_id, name, email.lower(), generate_password_hash(password), department),
            )
        except sqlite3.IntegrityError as error:
            raise click.ClickException("Could not create teacher: " + str(error))
        click.echo(f"Teacher {teacher_id} created.")

    @app.cli.command("create-student")
    @click.option("--id", "student_id", prompt=True)
    @click.option("--name", prompt=True)
    @click.option("--roll-number", prompt=True)
    @click.option("--email", default="")
    @click.option("--semester", type=int, default=None)
    @click.option("--department", default="")
    def create_student(student_id, name, roll_number, email, semester, department):
        """Provision a student; their roll number is their initial sign-in credential."""
        init_db()
        try:
            get_db().execute(
                """INSERT INTO students (student_id, name, roll_number, email, semester, department)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (student_id, name, roll_number, email.lower() or None, semester, department),
            )
        except sqlite3.IntegrityError as error:
            raise click.ClickException("Could not create student: " + str(error))
        click.echo(f"Student {student_id} created.")

    with app.app_context():
        init_db()
    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False)
