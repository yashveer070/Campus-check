FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    ATTENDANCE_DATABASE=/data/attendance.db

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --shell /usr/sbin/nologin attendance \
    && mkdir /data \
    && chown attendance:attendance /data

COPY --chown=attendance:attendance . ./

USER attendance
VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8080/healthz')"

# SQLite needs a single application process unless it is replaced with a network database.
CMD ["sh", "-c", "gunicorn --workers 1 --threads 4 --bind 0.0.0.0:${PORT:-8080} wsgi:app"]
