const RADII = { cardio: 100, resp: 86, heat: 72 };
const CIRC = Object.fromEntries(Object.entries(RADII).map(([k, r]) => [k, 2 * Math.PI * r]));

const arcCardio = document.getElementById("arcCardio");
const arcResp = document.getElementById("arcResp");
const arcHeat = document.getElementById("arcHeat");

[["cardio", arcCardio], ["resp", arcResp], ["heat", arcHeat]].forEach(([k, el]) => {
  el.style.strokeDasharray = `${CIRC[k]} ${CIRC[k]}`;
  el.style.strokeDashoffset = CIRC[k];
});

function setArc(el, key, pct) {
  const c = CIRC[key];
  el.style.strokeDashoffset = c * (1 - Math.min(100, Math.max(0, pct)) / 100);
}

function statusForScore(score) {
  if (score < 30) return { text: "normal", color: "var(--safe)" };
  if (score < 60) return { text: "caution", color: "var(--heat)" };
  if (score < 80) return { text: "elevated", color: "#E08A3E" };
  return { text: "critical", color: "var(--alert)" };
}

function showToast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(showToast._h);
  showToast._h = setTimeout(() => t.classList.remove("show"), 4000);
}

function drawSparkline(history) {
  const svg = document.getElementById("hrSpark");
  const w = 300, h = 60, pad = 4;
  if (!history.length) { svg.innerHTML = ""; return; }
  const vals = history.map(r => r.heart_rate);
  const min = Math.min(...vals) - 2, max = Math.max(...vals) + 2;
  const range = Math.max(1, max - min);
  const step = (w - pad * 2) / Math.max(1, vals.length - 1);
  const points = vals.map((v, i) => {
    const x = pad + i * step;
    const y = h - pad - ((v - min) / range) * (h - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  svg.innerHTML = `
    <polyline points="${points}" fill="none" stroke="#C1443C" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
  `;
}

function renderAlerts(alerts) {
  const list = document.getElementById("alertList");
  if (!alerts.length) {
    list.innerHTML = `<li class="alert-empty">No alerts yet — monitoring.</li>`;
    return;
  }
  list.innerHTML = alerts.map(a => {
    const time = new Date(a.ts * 1000).toLocaleTimeString();
    return `<li class="sev-${a.severity}">${a.message}<span class="alert-time">${a.category} · ${time}</span></li>`;
  }).join("");
}

let lastAlertCount = 0;

async function tick() {
  try {
    const res = await fetch("/api/state");
    const data = await res.json();

    // vitals
    document.getElementById("vHr").textContent = data.vitals.heart_rate;
    document.getElementById("vSpo2").textContent = data.vitals.spo2;
    document.getElementById("vTemp").textContent = data.vitals.body_temp;
    document.getElementById("vAct").textContent = data.vitals.activity;
    document.getElementById("vSleep").textContent = data.vitals.sleep_score;

    // environment
    document.getElementById("eTemp").textContent = data.environment.ambient_temp + "°C";
    document.getElementById("eHum").textContent = data.environment.humidity + "%";
    document.getElementById("eAqi").textContent = data.environment.aqi;
    document.getElementById("eHeat").textContent = data.environment.heat_index + "°C";

    // risk ring
    const r = data.risk;
    document.getElementById("riskScore").textContent = r.composite;
    const st = statusForScore(r.composite);
    const statusEl = document.getElementById("riskStatus");
    statusEl.textContent = st.text;
    statusEl.style.color = st.color;

    setArc(arcCardio, "cardio", r.sub_scores.cardio);
    setArc(arcResp, "resp", r.sub_scores.respiratory);
    setArc(arcHeat, "heat", r.sub_scores.heat);
    document.getElementById("subCardio").textContent = r.sub_scores.cardio;
    document.getElementById("subResp").textContent = r.sub_scores.respiratory;
    document.getElementById("subHeat").textContent = r.sub_scores.heat;
    document.getElementById("subFatigue").textContent = r.sub_scores.fatigue;

    drawSparkline(data.history);
    renderAlerts(data.alerts);

    if (data.alerts.length > lastAlertCount && data.new_alerts.length) {
      const worst = data.new_alerts.sort((a, b) => (a.severity === "critical" ? -1 : 1))[0];
      showToast(worst.message);
    }
    lastAlertCount = data.alerts.length;

  } catch (e) {
    console.error("state poll failed", e);
  }
}

document.querySelectorAll(".scenario-buttons button").forEach(btn => {
  btn.addEventListener("click", () => {
    fetch("/api/scenario", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ event: btn.dataset.event }),
    });
    showToast(`Scenario triggered: ${btn.dataset.event}`);
  });
});

document.getElementById("sosButton").addEventListener("click", async () => {
  const res = await fetch("/api/sos", { method: "POST" });
  const data = await res.json();
  showToast(data.message);
});

tick();
setInterval(tick, 3000);
