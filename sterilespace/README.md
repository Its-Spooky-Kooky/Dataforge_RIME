# SterileSpace (The Dirty-Hands / Sterile-Lab Voice Operating Copilot)

> Built for the **Rime Voice AI Hackathon**.

SterileSpace is an asynchronous, hands-free voice operating copilot designed for biosafety laboratories (BSL-2/3), pharmaceutical cleanrooms, and surgical pathology suites where touching screens, keyboards, or mice is physically impossible due to sterile double-gloving or hazardous bio-pathogens.

---

## 🌟 Key Features

1. **Voice-First Necessity**: Solves the cleanroom glove barrier where manual contact causes bio-contamination or breaches aseptic fields.
2. **Hard Voice Engineering: Interruption & Recovery**:
   - Sub-180ms user barge-in audio cutoff.
   - Long-running async tool fencing (`asyncio.Task.cancel()`) preventing zombie hardware writes and dirty database commits.
3. **Hard Voice Engineering: Pronunciation & Delivery**:
   - Scientific preprocessor (`normalizer.py`) converts alphanumeric vials (`4B` -> `four-bee`), units (`0.5µL` -> `zero point five microliters`), pH levels (`pH 7.4` -> `p-H seven point four`), and fan speeds (`3000 RPM` -> `three thousand R-P-M`).
4. **Rime Cloud TTS Integration**:
   - Native integration with Rime Coda and Mist v3 models (`astra` and `luna` speakers).
   - Dual interface: LiveKit agent pipeline and direct streaming HTTP proxy.
5. **Reactive Cleanroom Laboratory HUD**:
   - Real-time sample inventory spreadsheet with green/red commit/abort flash animations.
   - Animated SVG/CSS 3D ventilator fan widget that spins up to 3600 RPM in real time.
   - HTML5 Canvas oscilloscope audio waveform visualizer.
   - Live telemetry terminal displaying barge-in benchmarks and phonetic diffs.

---

## 📁 Repository Structure

```
sterilespace/
├── .env.example              # Environment variables template
├── README.md                 # Project documentation
├── RIME_EVIDENCE.md          # Official Hackathon Evidence & Benchmark Report
├── requirements.txt          # Python dependencies
├── package.json              # Node project scripts
├── agent/
│   ├── __init__.py
│   ├── main.py               # LiveKit agent worker with Rime TTS & tools
│   ├── normalizer.py         # Phonetic & scientific text preprocessor
│   └── state_manager.py      # Cancellation token & session manager
├── server/
│   ├── app.py                # FastAPI backend with WebSockets for telemetry & IoT
│   └── mock_iot.py           # Simulated lab fan & temperature/oxidation store
├── web/
│   ├── index.html            # Real-time reactive lab HUD
│   ├── app.js                # WebRTC client & LiveKit audio track subscriber
│   └── style.css             # Clean, high-contrast dark laboratory UI
└── evals/
    ├── test_interruption.py  # Automated barge-in benchmark script
    └── fixtures.json         # Test spoken inputs and expected phonetic mappings
```

---

## 🚀 Quickstart Guide

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment (Optional)
Copy `.env.example` to `.env` and add your API keys:
```bash
cp .env.example .env
```
*(Note: SterileSpace is designed with zero-breakage resilience. If keys are omitted, high-fidelity synthetic fallbacks allow full testing and UI demonstration out of the box).*

### 3. Run Automated Evaluation & Benchmark
```bash
python evals/test_interruption.py
```

### 4. Start Laboratory Telemetry Server & Web HUD
```bash
python -m uvicorn server.app:app --host 0.0.0.0 --port 8000 --reload
```
Open **[http://localhost:8000](http://localhost:8000)** in your browser.

### 5. Start LiveKit Agent Worker (Optional for Live WebRTC)
```bash
python agent/main.py dev
```

---

## 📊 Evaluation & Evidence Summary

- **Phonetic Normalization Accuracy**: **100.0%** (6/6 Test Fixtures Passed)
- **Average Interruption Cutoff Latency**: **0.11 ms** (Target: `< 180 ms` — **PASSED**)
- **State Integrity on Barge-In**: **100% Rollback** (Zero corrupt commits on cancelled tasks)
- Detailed results available in [`RIME_EVIDENCE.md`](RIME_EVIDENCE.md).
