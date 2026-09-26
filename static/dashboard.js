const dashboardCsrf = document.querySelector('meta[name="csrf-token"]').content;
const sessionToken = window.CAMPUSCHECK_SESSION_TOKEN;
const attendanceBody = document.getElementById("attendance-body");

function cell(text) {
  const td = document.createElement("td");
  td.textContent = text ?? "—";
  return td;
}

function displayTime(value) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

async function refreshDashboard() {
  try {
    const response = await fetch("/api/teacher/dashboard/" + encodeURIComponent(sessionToken), { credentials: "same-origin" });
    if (!response.ok) throw new Error("Refresh failed");
    const data = await response.json();
    document.getElementById("stat-present").textContent = data.stats.present;
    document.getElementById("stat-absent").textContent = data.stats.absent;
    document.getElementById("stat-percentage").textContent = data.stats.percentage + "%";
    attendanceBody.replaceChildren();
    if (!data.attendance.length) {
      const row = document.createElement("tr");
      const empty = cell("No attendance has been recorded yet.");
      empty.colSpan = 6;
      empty.className = "empty";
      row.append(empty);
      attendanceBody.append(row);
    }
    for (const attendee of data.attendance) {
      const row = document.createElement("tr");
      row.append(cell(attendee.roll_number), cell(attendee.name), cell(displayTime(attendee.timestamp)), cell(attendee.client_ip));
      const location = attendee.latitude == null ? "Manual" : Number(attendee.latitude).toFixed(5) + ", " + Number(attendee.longitude).toFixed(5) + " (±" + Math.round(attendee.accuracy || 0) + "m)";
      row.append(cell(location));
      const status = document.createElement("span");
      status.className = "status " + (attendee.is_flagged ? "flagged" : "good");
      status.textContent = attendee.is_flagged ? "Review" : "Verified";
      const statusCell = document.createElement("td");
      statusCell.append(status);
      row.append(statusCell);
      attendanceBody.append(row);
    }
    document.getElementById("updated-at").textContent = "Updated " + new Date().toLocaleTimeString();
  } catch {
    document.getElementById("updated-at").textContent = "Unable to refresh — retrying";
  }
}

document.getElementById("manual-form").addEventListener("submit", async event => {
  event.preventDefault();
  const message = document.getElementById("manual-message");
  const input = document.getElementById("manual-student-id");
  try {
    const response = await fetch("/api/teacher/dashboard/" + encodeURIComponent(sessionToken) + "/manual-attendance", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": dashboardCsrf },
      body: JSON.stringify({ student_id: input.value.trim() })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not record attendance.");
    message.textContent = data.message;
    message.style.color = "var(--green)";
    input.value = "";
    refreshDashboard();
  } catch (error) {
    message.textContent = error.message;
    message.style.color = "var(--red)";
  }
});

refreshDashboard();
setInterval(refreshDashboard, 10000);
