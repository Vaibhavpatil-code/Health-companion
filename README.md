# Guardian — Personal Health Companion (SIH26181 prototype)

A minimal, runnable prototype for the "secure, AI-powered Personal Health Companion"
problem statement (Qualcomm / MedTech-BioTech-HealthTech).

## What this demonstrates

- **On-device inference boundary**: `app.py`'s `assess()` function is the "edge AI" —
  it runs entirely on the process serving the page, with no external API calls. In a
  real mobile/wearable build this logic (or a learned model doing the same job) would
  run via TFLite / ONNX Runtime Mobile on the Qualcomm NPU, not in the cloud.
- **Privacy-by-design storage**: readings and alerts are written to a local SQLite file
  (`health_local.db`) and nothing leaves the machine. That file is the stand-in for
  on-device encrypted storage.
- **Disaster-specific risk logic**: heat index (NOAA formula), AQI-linked respiratory
  risk, dehydration pattern detection (heat + activity + HR), and fall/SOS handling.
- **Offline-first framing**: the dashboard has no dependency on a live network call for
  its core function — everything after the vitals/environment are "sensed" is computed
  locally.

## What it does NOT do (by design, for a hackathon prototype)

- No real sensor SDK integration (BLE/health-connect APIs) — vitals are simulated with
  a random walk so the dashboard tells a coherent story over time.
- No real ML model — the risk engine uses transparent, explainable rule thresholds.
  These are easy to justify to a judge and are exactly the kind of "safety net" tier
  a real system keeps even after adding a learned anomaly model.
- No real caregiver notification — SOS is simulated in-app.

## Running it

```bash
pip install -r requirements.txt
python app.py
```

Then open http://localhost:5000

## Where to take it next (if you build past the prototype)

1. Swap `SensorState.step()` for real sensor reads (Health Connect / BLE GATT for
   wearables).
2. Replace/augment `assess()` with a small on-device anomaly model (e.g. an autoencoder
   trained per-user on their own baseline, exported to TFLite) while keeping the rule
   thresholds as a fallback safety net.
3. Add an opt-in, encrypted sync channel for caregiver sharing only (not required for
   core safety functions — matches the "operates without connectivity" requirement).
4. Add per-user baselining: right now thresholds are population-level; a real system
   should adapt to the individual's resting HR, sleep pattern, etc. over time.
