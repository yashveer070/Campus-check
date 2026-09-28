import QrScanner from "https://cdn.jsdelivr.net/npm/qr-scanner@1.4.2/qr-scanner.min.js";

QrScanner.WORKER_PATH = "https://cdn.jsdelivr.net/npm/qr-scanner@1.4.2/qr-scanner-worker.min.js";

const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
const video = document.getElementById("scanner");
const message = document.getElementById("scan-message");
const retry = document.getElementById("retry-camera");
const queueKey = "campuscheck-offline-checkins";
let scanner;
let submitting = false;

function setMessage(text) {
  message.textContent = text;
}

async function fingerprint() {
  const values = [navigator.userAgent, navigator.language, screen.width, screen.height, screen.colorDepth, Intl.DateTimeFormat().resolvedOptions().timeZone].join("|");
  if (window.crypto && window.crypto.subtle) {
    const buffer = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(values));
    return Array.from(new Uint8Array(buffer)).map(value => value.toString(16).padStart(2, "0")).join("");
  }
  return values.slice(0, 120);
}

function queueRead() {
  try { return JSON.parse(localStorage.getItem(queueKey) || "[]"); } catch { return []; }
}

function queueWrite(entries) {
  localStorage.setItem(queueKey, JSON.stringify(entries.slice(-5)));
}

function queueCheckin(payload) {
  const pending = queueRead();
  if (!pending.some(item => item.session_token === payload.session_token)) pending.push(payload);
  queueWrite(pending);
}

function locationRequest() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) return reject(new Error("This browser does not support geolocation."));
    navigator.geolocation.getCurrentPosition(resolve, reject, { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
  });
}

function tokenFromScan(value) {
  try {
    const url = new URL(value);
    return url.searchParams.get("token");
  } catch {
    return /^[A-Za-z0-9_-]{16,}$/.test(value) ? value : null;
  }
}

async function sendAttendance(payload) {
  const response = await fetch("/api/mark-attendance", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
    credentials: "same-origin",
    body: JSON.stringify(payload)
  });
  let data = {};
  try { data = await response.json(); } catch {}
  if (!response.ok) throw new Error(data.error || "Attendance could not be recorded.");
  return data;
}

async function flushQueue() {
  if (!navigator.onLine) return;
  const pending = queueRead();
  if (!pending.length) return;
  const remaining = [];
  for (const payload of pending) {
    try { await sendAttendance(payload); } catch { remaining.push(payload); }
  }
  queueWrite(remaining);
  if (pending.length > remaining.length) setMessage("Saved queued attendance when the connection returned.");
}

async function beginCheckin(token) {
  if (submitting) return;
  submitting = true;
  if (scanner) scanner.stop();
  setMessage("Getting high-accuracy classroom location…");
  try {
    const position = await locationRequest();
    const payload = {
      session_token: token,
      latitude: position.coords.latitude,
      longitude: position.coords.longitude,
      accuracy: position.coords.accuracy,
      device_fingerprint: await fingerprint()
    };
    setMessage("Validating attendance…");
    try {
      const result = await sendAttendance(payload);
      setMessage(result.flagged ? "Attendance saved for review." : "Attendance marked successfully ✓");
    } catch (error) {
      if (!navigator.onLine || error instanceof TypeError) {
        queueCheckin(payload);
        setMessage("Offline: check-in is queued and will retry when connected.");
      } else {
        throw error;
      }
    }
  } catch (error) {
    setMessage(error.message || "Location permission is required to check in.");
    submitting = false;
    if (scanner) startScanner();
  }
}

function scanResult(result) {
  const token = tokenFromScan(result.data || result);
  if (!token) {
    setMessage("That code is not a CampusCheck attendance code.");
    return;
  }
  beginCheckin(token);
}

async function startScanner() {
  retry.classList.add("hidden");
  try {
    if (!scanner) scanner = new QrScanner(video, scanResult, { preferredCamera: "environment", highlightScanRegion: false, returnDetailedScanResult: true });
    await scanner.start();
    setMessage("Point your camera at the teacher's QR code.");
  } catch (error) {
    setMessage("Camera permission is required. " + (error.message || ""));
    retry.classList.remove("hidden");
  }
}

retry.addEventListener("click", startScanner);
window.addEventListener("online", flushQueue);
flushQueue();
if (window.CAMPUSCHECK_INITIAL_TOKEN) {
  beginCheckin(window.CAMPUSCHECK_INITIAL_TOKEN);
} else {
  startScanner();
}
