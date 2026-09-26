const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
const state = { location: null, expiresAt: null, timer: null };
const detail = document.getElementById("location-detail");
const locationState = document.getElementById("location-state");
const locationButton = document.getElementById("location-button");
const generateButton = document.getElementById("generate-button");
const form = document.getElementById("session-form");

function message(text, good = false) {
  locationState.textContent = text;
  locationState.style.color = good ? "var(--green)" : "var(--orange)";
}

function requestLocation() {
  if (!navigator.geolocation) {
    message("Location is unavailable");
    detail.textContent = "This browser does not support geolocation.";
    return;
  }
  locationButton.disabled = true;
  message("Locating classroom…");
  detail.textContent = "Approve the high-accuracy location request.";
  navigator.geolocation.getCurrentPosition(
    position => {
      state.location = position.coords;
      message("Classroom location captured", true);
      detail.textContent = position.coords.latitude.toFixed(6) + ", " + position.coords.longitude.toFixed(6) + " · ±" + Math.round(position.coords.accuracy) + " m";
      generateButton.disabled = false;
      locationButton.disabled = false;
    },
    error => {
      message("Location permission is required");
      detail.textContent = error.message;
      locationButton.disabled = false;
    },
    { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }
  );
}

function updateTimer() {
  const seconds = Math.max(0, Math.ceil((state.expiresAt - Date.now()) / 1000));
  document.getElementById("countdown").textContent = String(Math.floor(seconds / 60)).padStart(2, "0") + ":" + String(seconds % 60).padStart(2, "0");
  if (seconds === 0) {
    clearInterval(state.timer);
    document.getElementById("countdown").textContent = "Expired";
    // Classroom coordinates are already captured, so renew without making the
    // teacher repeat the location prompt every minute.
    setTimeout(() => form.requestSubmit(), 750);
  }
}

locationButton.addEventListener("click", requestLocation);
form.addEventListener("submit", async event => {
  event.preventDefault();
  if (!state.location) return requestLocation();
  generateButton.disabled = true;
  generateButton.textContent = "Generating…";
  try {
    const response = await fetch("/api/teacher/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
      body: JSON.stringify({
        subject_code: document.getElementById("subject-code").value,
        latitude: state.location.latitude,
        longitude: state.location.longitude
      })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not generate the QR code.");
    document.getElementById("qr-image").src = data.qr_data_url;
    document.getElementById("result-subject").textContent = data.subject_code;
    document.getElementById("result-token").textContent = data.session_token;
    document.getElementById("result-location").textContent = state.location.latitude.toFixed(5) + ", " + state.location.longitude.toFixed(5);
    document.getElementById("dashboard-link").href = data.dashboard_url;
    document.getElementById("qr-result").classList.remove("hidden");
    state.expiresAt = new Date(data.expires_at).getTime();
    clearInterval(state.timer);
    updateTimer();
    state.timer = setInterval(updateTimer, 500);
  } catch (error) {
    detail.textContent = error.message;
    message("Could not create session");
  } finally {
    generateButton.disabled = false;
    generateButton.textContent = "Generate secure QR";
  }
});
