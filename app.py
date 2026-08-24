"""
Personal Health Companion — SIH26181 prototype
Qualcomm theme: privacy-preserving, on-device health monitoring & disaster-resilience alerts.

WHY THIS SHAPE
---------------
Real deployments run inference on-device (TFLite / ONNX-Runtime-Mobile / Qualcomm
Hexagon NPU). This prototype can't access real wearable sensors, so it simulates the
sensor stream, but the RISK ENGINE below is written the same way an on-device engine
would be: small, deterministic, explainable rules (a "safety net" tier) that could sit
in front of, or alongside, a learned anomaly model. Nothing here calls out to a network
service for inference — the /api/state endpoint IS the "edge device" boundary.

All readings are persisted to a local SQLite file (health_local.db) only. Nothing is
transmitted anywhere. That's intentional: it's standing in for "data never leaves the
device" from the problem statement.

Run:
    pip install -r requirements.txt
    python app.py
Then open http://localhost:5000
"""

import math
import random
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

DB_PATH = Path(__file__).parent / "health_local.db"

# --------------------------------------------------------------------------------------
# Local-only storage (stand-in for on-device encrypted storage)
# --------------------------------------------------------------------------------------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            heart_rate REAL, spo2 REAL, body_temp REAL,
            activity REAL, sleep_score REAL,
            ambient_temp REAL, humidity REAL, aqi REAL,
            heat_index REAL, risk_score REAL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            severity TEXT, category TEXT, message TEXT
        )
        """
    )
    conn.commit()
    conn.close()


init_db()

# --------------------------------------------------------------------------------------
# Sensor simulation — a stand-in for the phone/wearable sensor SDK layer.
# Uses a slow random walk so the dashboard tells a coherent story over time
# instead of pure noise, plus an occasional injected "event" to show alerts firing.
# --------------------------------------------------------------------------------------

class SensorState:
    def __init__(self):
        self.heart_rate = 72.0
        self.spo2 = 98.0
        self.body_temp = 36.8
        self.activity = 20.0       # steps/min equivalent
        self.sleep_score = 78.0
        self.ambient_temp = 34.0   # deg C — Indian pre-monsoon baseline
        self.humidity = 55.0       # %
        self.aqi = 90.0
        self.tick = 0
        self.forced_event = None   # lets the demo trigger a scenario on request

    def step(self):
        self.tick += 1

        def walk(val, drift, lo, hi, noise=1.0):
            val += random.uniform(-noise, noise) + drift
            return max(lo, min(hi, val))

        drift = {"hr": 0, "temp": 0, "amb": 0, "aqi": 0, "spo2": 0}

        if self.forced_event == "heatwave":
            drift.update(amb=1.4, hr=1.2, temp=0.15)
        elif self.forced_event == "pollution":
            drift.update(aqi=6.0, spo2=-0.2)
        elif self.forced_event == "fall":
            self.forced_event = None  # one-shot, handled by caller
        elif self.forced_event == "clear":
            drift = {"hr": -1.0, "temp": -0.05, "amb": -0.6, "aqi": -3.0, "spo2": 0.1}
            if self.ambient_temp <= 33 and self.aqi <= 100:
                self.forced_event = None

        self.heart_rate = walk(self.heart_rate, drift["hr"], 48, 160, 1.5)
        self.spo2 = walk(self.spo2, drift["spo2"], 82, 99, 0.4)
        self.body_temp = walk(self.body_temp, drift["temp"], 35.5, 40.5, 0.08)
        self.activity = walk(self.activity, 0, 0, 100, 4)
        self.sleep_score = walk(self.sleep_score, 0, 30, 95, 0.5)
        self.ambient_temp = walk(self.ambient_temp, drift["amb"], 22, 48, 0.3)
        self.humidity = walk(self.humidity, 0, 20, 95, 1.0)
        self.aqi = walk(self.aqi, drift["aqi"], 15, 400, 2.0)

    def trigger(self, event):
        self.forced_event = event


sensors = SensorState()

# --------------------------------------------------------------------------------------
# On-device risk engine — deterministic, explainable rules.
# Each function returns (score_0_100, alerts[]) so the UI can show WHY a score fired,
# which matters for trust in a health-safety product.
# --------------------------------------------------------------------------------------

def heat_index_celsius(temp_c, rh):
    """NOAA heat index approximation, adapted to Celsius input/output."""
    t = temp_c * 9 / 5 + 32
    hi = (
        -42.379 + 2.04901523 * t + 10.14333127 * rh
        - 0.22475541 * t * rh - 0.00683783 * t * t
        - 0.05481717 * rh * rh + 0.00122874 * t * t * rh
        + 0.00085282 * t * rh * rh - 0.00000199 * t * t * rh * rh
    )
    if t < 80:
        hi = 0.5 * (t + 61.0 + (t - 68.0) * 1.2 + rh * 0.094)
    return round((hi - 32) * 5 / 9, 1)


def assess(s: SensorState):
    alerts = []
    hi = heat_index_celsius(s.ambient_temp, s.humidity)

    # --- Cardiovascular -----------------------------------------------------
    cardio = 0
    if s.heart_rate > 130 or s.heart_rate < 45:
        cardio = 90
        alerts.append(("critical", "cardiac", f"Heart rate {s.heart_rate:.0f} bpm is outside safe resting range."))
    elif s.heart_rate > 110:
        cardio = 55
        alerts.append(("warning", "cardiac", f"Elevated heart rate ({s.heart_rate:.0f} bpm) — monitor for exertion or stress."))
    else:
        cardio = max(0, (s.heart_rate - 60) * 1.2)

    # --- Respiratory ---------------------------------------------------------
    resp = 0
    if s.spo2 < 90:
        resp = 95
        alerts.append(("critical", "respiratory", f"SpO2 {s.spo2:.0f}% is critically low — seek medical attention."))
    elif s.spo2 < 94:
        resp = 60
        alerts.append(("warning", "respiratory", f"SpO2 {s.spo2:.0f}% is below normal range."))
    if s.aqi > 200:
        resp = max(resp, 70)
        alerts.append(("warning", "environment", f"AQI {s.aqi:.0f} (Very Poor) — limit outdoor exposure, consider a mask."))
    elif s.aqi > 300:
        resp = 90

    # --- Heat stress -----------------------------------------------------
    heat = 0
    if hi >= 54:
        heat = 95
        alerts.append(("critical", "heat", f"Heat index {hi}°C — extreme danger of heatstroke."))
    elif hi >= 41:
        heat = 75
        alerts.append(("warning", "heat", f"Heat index {hi}°C — high heat stress risk, hydrate and rest in shade."))
    elif hi >= 32:
        heat = 40
        alerts.append(("info", "heat", f"Heat index {hi}°C — caution advised during outdoor activity."))

    # --- Fatigue / dehydration proxy -----------------------------------------
    fatigue = 0
    if s.sleep_score < 45 and s.activity > 50:
        fatigue = 60
        alerts.append(("warning", "fatigue", "Poor sleep recovery combined with sustained activity — fatigue risk rising."))
    dehydration_signal = (heat > 50 and s.activity > 40 and s.heart_rate > 95)
    if dehydration_signal:
        fatigue = max(fatigue, 70)
        alerts.append(("warning", "dehydration", "Heat + activity + elevated HR pattern suggests dehydration risk."))

    composite = round(0.3 * cardio + 0.3 * resp + 0.3 * heat + 0.1 * fatigue)
    composite = max(0, min(100, composite))

    return {
        "heat_index": hi,
        "composite_risk": composite,
        "sub_scores": {"cardio": round(cardio), "respiratory": round(resp), "heat": round(heat), "fatigue": round(fatigue)},
        "alerts": alerts,
    }


def store_reading(s: SensorState, result):
    conn = get_db()
    conn.execute(
        """INSERT INTO readings
        (ts, heart_rate, spo2, body_temp, activity, sleep_score, ambient_temp, humidity, aqi, heat_index, risk_score)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (time.time(), s.heart_rate, s.spo2, s.body_temp, s.activity, s.sleep_score,
         s.ambient_temp, s.humidity, s.aqi, result["heat_index"], result["composite_risk"]),
    )
    for severity, category, message in result["alerts"]:
        if severity in ("warning", "critical"):
            conn.execute(
                "INSERT INTO alerts (ts, severity, category, message) VALUES (?,?,?,?)",
                (time.time(), severity, category, message),
            )
    conn.commit()
    # keep local history bounded — this is a device, not a data warehouse
    conn.execute(
        "DELETE FROM readings WHERE id NOT IN (SELECT id FROM readings ORDER BY id DESC LIMIT 200)"
    )
    conn.execute(
        "DELETE FROM alerts WHERE id NOT IN (SELECT id FROM alerts ORDER BY id DESC LIMIT 30)"
    )
    conn.commit()
    conn.close()


def recent_readings(limit=30):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM readings ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


def recent_alerts(limit=8):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def api_state():
    sensors.step()
    result = assess(sensors)
    store_reading(sensors, result)

    return jsonify({
        "vitals": {
            "heart_rate": round(sensors.heart_rate),
            "spo2": round(sensors.spo2, 1),
            "body_temp": round(sensors.body_temp, 1),
            "activity": round(sensors.activity),
            "sleep_score": round(sensors.sleep_score),
        },
        "environment": {
            "ambient_temp": round(sensors.ambient_temp, 1),
            "humidity": round(sensors.humidity),
            "aqi": round(sensors.aqi),
            "heat_index": result["heat_index"],
        },
        "risk": {
            "composite": result["composite_risk"],
            "sub_scores": result["sub_scores"],
        },
        "new_alerts": [{"severity": a, "category": c, "message": m} for a, c, m in result["alerts"]],
        "alerts": recent_alerts(),
        "history": recent_readings(),
        "device_status": {"local_ai": "active", "network": "offline-capable", "storage": "on-device (SQLite)"},
        "server_time": datetime.now().strftime("%H:%M:%S"),
    })


@app.route("/api/scenario", methods=["POST"])
def api_scenario():
    """Lets the demo operator (judge) trigger a scenario to show the alert pipeline."""
    event = request.json.get("event") if request.is_json else None
    if event == "fall":
        conn = get_db()
        conn.execute(
            "INSERT INTO alerts (ts, severity, category, message) VALUES (?,?,?,?)",
            (time.time(), "critical", "fall", "Sudden motion signature consistent with a fall was detected."),
        )
        conn.commit()
        conn.close()
    elif event in ("heatwave", "pollution", "clear"):
        sensors.trigger(event)
    return jsonify({"ok": True, "event": event})


@app.route("/api/sos", methods=["POST"])
def api_sos():
    """
    Simulated SOS. In a real deployment this would use the OS's emergency /
    caregiver-share APIs and only fire with explicit user permission. Location
    here is a placeholder — never collected without consent.
    """
    conn = get_db()
    conn.execute(
        "INSERT INTO alerts (ts, severity, category, message) VALUES (?,?,?,?)",
        (time.time(), "critical", "sos", "Manual SOS triggered by user — caregiver notification simulated."),
    )
    conn.commit()
    conn.close()
    return jsonify({
        "ok": True,
        "message": "SOS simulated: caregiver + nearest facility would be notified with your last known location (opt-in only).",
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)
