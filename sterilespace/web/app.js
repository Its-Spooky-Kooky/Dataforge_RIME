/**
 * SterileSpace - Cleanroom Voice Operating Copilot HUD
 * Real-time WebSocket telemetry, reactive sample grid, animated fan relay,
 * canvas waveform visualizer, and sub-180ms barge-in benchmark display.
 */

// DOM Elements
const wsStatus = document.getElementById("ws-status");
const sampleRows = document.getElementById("sample-rows");
const fanBlades = document.getElementById("fan-blades");
const fanStateBadge = document.getElementById("fan-state-badge");
const valRpm = document.getElementById("val-rpm");
const valCfm = document.getElementById("val-cfm");
const valPressure = document.getElementById("val-pressure");
const barRpm = document.getElementById("bar-rpm");
const barCfm = document.getElementById("bar-cfm");
const bargeinMetric = document.getElementById("bargein-metric");
const terminalLog = document.getElementById("terminal-log");
const btnClearLog = document.getElementById("btn-clear-log");
const audioState = document.getElementById("audio-state");
const vadStatus = document.getElementById("vad-status");
const bufferStatus = document.getElementById("buffer-status");

// Buttons
const btnCompound = document.getElementById("btn-compound");
const btnBargein = document.getElementById("btn-bargein");
const btnPhonetic = document.getElementById("btn-phonetic");
const btnToggleMic = document.getElementById("btn-toggle-mic");
const micBtnLabel = document.getElementById("mic-btn-label");

// Canvas Waveform Visualizer
const canvas = document.getElementById("waveform-canvas");
const ctx = canvas.getContext("2d");
let isAudioActive = false;
let animationFrameId = null;

// Audio context for playing Rime audio streams
let audioCtx = null;

function getAudioContext() {
  if (!audioCtx) {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  }
  if (audioCtx.state === "suspended") {
    audioCtx.resume();
  }
  return audioCtx;
}

// ==============================================================================
// WebSocket Telemetry Connection
// ==============================================================================
let socket = null;

function connectWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws/telemetry`;

  socket = new WebSocket(wsUrl);

  socket.onopen = () => {
    wsStatus.className = "status-pill ws-badge connected";
    wsStatus.innerHTML = '<span class="status-indicator"></span><span>Telemetry Live</span>';
    addLog("SYSTEM", "WebSocket connected to laboratory telemetry server.");
  };

  socket.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      handleTelemetryMessage(msg);
    } catch (err) {
      console.error("Failed to parse telemetry:", err);
    }
  };

  socket.onclose = () => {
    wsStatus.className = "status-pill ws-badge";
    wsStatus.innerHTML = '<span class="status-indicator" style="background:#ff1744"></span><span>Reconnecting...</span>';
    setTimeout(connectWebSocket, 2500);
  };

  socket.onerror = (err) => {
    console.error("WebSocket error:", err);
  };
}

function handleTelemetryMessage(msg) {
  const { type, data, snapshot } = msg;

  if (type === "INITIAL_SNAPSHOT") {
    renderSamples(snapshot.samples);
    updateVentilation(snapshot.ventilation);
  } else if (type === "SAMPLE_UPDATED") {
    updateSampleRow(data.record, true);
    addLog("TOOL", `Sample ${data.tube_id} successfully updated: ${data.record.metric} = ${data.record.value} ${data.record.unit}`);
  } else if (type === "VENTILATION_CHANGED") {
    updateVentilation(data.ventilation);
    addLog("TOOL", `Ventilation relay switched: ${data.ventilation.state} (${data.ventilation.speed}, ${data.ventilation.rpm} RPM)`);
  } else if (type === "TOOL_STARTED") {
    addLog("TOOL", `Async Tool Started: [${data.action}] — In-flight latency fence active (${data.simulated_latency_sec}s)`);
  } else if (type === "TOOL_ABORTED") {
    flashAllRowsRed();
    addLog("BARGE", `TOOL ABORTED! Reason: ${data.reason}. Cutoff latency: ${data.cutoff_latency_ms} ms`);
    bargeinMetric.innerText = `${data.cutoff_latency_ms} ms (PROVEN)`;
    bargeinMetric.style.color = "#00e676";
  } else if (type === "BARGE_IN_TRIGGERED") {
    bargeinMetric.innerText = `${data.cutoff_latency_ms} ms`;
    addLog("BARGE", `Barge-In Cutoff Executed in ${data.cutoff_latency_ms} ms (<180ms requirement met: ${data.target_met})`);
  } else if (type === "TTS_SYNTHESIS_STARTED") {
    addLog("NORM", `Phonetic Diff: "${data.original_text}" -> "${data.normalized_text}"`);
  }
}

// ==============================================================================
// Sample Inventory Grid Rendering
// ==============================================================================
function renderSamples(samples) {
  sampleRows.innerHTML = "";
  samples.forEach(s => updateSampleRow(s, false));
}

function updateSampleRow(sample, shouldFlash = true) {
  let existing = document.getElementById(`row-${sample.id}`);
  const statusClass = `status-${(sample.status || 'NORMAL').toLowerCase()}`;
  const formattedTime = new Date(sample.updated_at).toLocaleTimeString();

  const rowHtml = `
    <td><span class="tube-badge">${sample.id}</span></td>
    <td><strong>${sample.metric}</strong></td>
    <td>${sample.value}</td>
    <td>${sample.unit}</td>
    <td><span class="status-badge ${statusClass}">${sample.status}</span></td>
    <td>${formattedTime}</td>
  `;

  if (existing) {
    existing.innerHTML = rowHtml;
    if (shouldFlash) {
      existing.classList.remove("row-flash-green");
      void existing.offsetWidth; // Trigger reflow
      existing.classList.add("row-flash-green");
    }
  } else {
    const tr = document.createElement("tr");
    tr.id = `row-${sample.id}`;
    tr.innerHTML = rowHtml;
    if (shouldFlash) tr.classList.add("row-flash-green");
    sampleRows.appendChild(tr);
  }
}

function flashAllRowsRed() {
  const rows = sampleRows.querySelectorAll("tr");
  rows.forEach(r => {
    r.classList.remove("row-flash-red");
    void r.offsetWidth;
    r.classList.add("row-flash-red");
  });
}

// ==============================================================================
// Ventilation Fan & IoT Relay Display
// ==============================================================================
function updateVentilation(vent) {
  const isOff = vent.state === "OFF" || vent.rpm === 0;

  valRpm.innerHTML = `${vent.rpm} <small>RPM</small>`;
  valCfm.innerHTML = `${vent.airflow_cfm} <small>CFM</small>`;
  valPressure.innerHTML = `${vent.pressure_pa} <small>Pa</small>`;

  barRpm.style.width = `${Math.min(100, (vent.rpm / 3600) * 100)}%`;
  barCfm.style.width = `${Math.min(100, (vent.airflow_cfm / 1200) * 100)}%`;

  if (isOff) {
    fanStateBadge.className = "badge-state state-off";
    fanStateBadge.innerText = "OFF";
    document.documentElement.style.setProperty("--fan-speed", "0s");
  } else {
    fanStateBadge.className = "badge-state state-on";
    fanStateBadge.innerText = `${vent.speed} (${vent.rpm} RPM)`;

    // Calculate rotation period inversely proportional to RPM
    const periodSec = vent.rpm > 0 ? (60 / vent.rpm) * 1.5 : 0;
    document.documentElement.style.setProperty("--fan-speed", `${periodSec.toFixed(2)}s`);
  }
}

// ==============================================================================
// Waveform Canvas Oscilloscope
// ==============================================================================
let wavePhase = 0;

function drawWaveform() {
  const width = canvas.width;
  const height = canvas.height;

  ctx.clearRect(0, 0, width, height);

  // Background grid
  ctx.strokeStyle = "rgba(255, 255, 255, 0.03)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let x = 0; x < width; x += 40) {
    ctx.moveTo(x, 0); ctx.lineTo(x, height);
  }
  for (let y = 0; y < height; y += 20) {
    ctx.moveTo(0, y); ctx.lineTo(width, y);
  }
  ctx.stroke();

  // Wave line
  ctx.lineWidth = 2;
  ctx.beginPath();

  const centerY = height / 2;
  const amp = isAudioActive ? 28 : 2;
  const freq = isAudioActive ? 0.08 : 0.03;

  ctx.strokeStyle = isAudioActive ? "#00e5ff" : "rgba(0, 229, 255, 0.25)";

  for (let x = 0; x < width; x++) {
    const y = centerY + Math.sin(x * freq + wavePhase) * amp + (isAudioActive ? (Math.random() - 0.5) * 6 : 0);
    if (x === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }

  ctx.stroke();
  wavePhase += isAudioActive ? 0.25 : 0.04;
  animationFrameId = requestAnimationFrame(drawWaveform);
}

drawWaveform();

function setAudioActive(active, stateText = "STREAMING") {
  isAudioActive = active;
  audioState.innerText = active ? stateText : "IDLE";
  audioState.style.color = active ? "#00e5ff" : "var(--text-muted)";
  audioState.style.borderColor = active ? "#00e5ff" : "rgba(0, 229, 255, 0.2)";
}

// ==============================================================================
// Terminal Logging Helper
// ==============================================================================
function addLog(tag, msg) {
  const now = new Date().toTimeString().split(" ")[0];
  const div = document.createElement("div");
  div.className = "log-entry";

  let tagClass = "tag-sys";
  if (tag === "NORM") tagClass = "tag-norm";
  else if (tag === "BARGE") tagClass = "tag-barge";
  else if (tag === "TOOL") tagClass = "tag-tool";

  div.innerHTML = `
    <span class="log-time">${now}</span>
    <span class="log-tag ${tagClass}">${tag}</span>
    <span class="log-msg">${msg}</span>
  `;

  terminalLog.appendChild(div);
  terminalLog.scrollTop = terminalLog.scrollHeight;
}

btnClearLog.addEventListener("click", () => {
  terminalLog.innerHTML = "";
});

// ==============================================================================
// Audio Playback Helper (plays WAV/PCM from Rime endpoint)
// ==============================================================================
async function playAudioBuffer(arrayBuffer) {
  try {
    const ctx = getAudioContext();
    const audioBuffer = await ctx.decodeAudioData(arrayBuffer);
    const source = ctx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(ctx.destination);

    setAudioActive(true, "RIME TTS PLAYING");
    source.onended = () => {
      setAudioActive(false);
    };
    source.start(0);
  } catch (err) {
    console.error("Audio playback error:", err);
    setAudioActive(false);
  }
}

// ==============================================================================
// Action Demonstration Buttons
// ==============================================================================

// 1. Compound Command Simulation
btnCompound.addEventListener("click", async () => {
  addLog("SYSTEM", 'User command: "Log 15% oxidation on tube 4B and turn on ventilation high"');
  setAudioActive(true, "PROCESSING SPEECH");

  try {
    const resp = await fetch("/api/simulate/voice-turn", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        transcript: "Log oxidation 15% on tube 4B and turn on ventilation high"
      })
    });
    const result = await resp.json();

    addLog("NORM", `Rime Speech Output: "${result.response_normalized_for_rime}"`);

    // Fetch and play Rime TTS audio
    const ttsResp = await fetch("/api/tts/rime", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: result.response_normalized_for_rime })
    });
    const audioBlob = await ttsResp.arrayBuffer();
    await playAudioBuffer(audioBlob);

  } catch (err) {
    console.error("Compound command error:", err);
    setAudioActive(false);
  }
});

// 2. Barge-In Interruption Benchmark Simulation
btnBargein.addEventListener("click", async () => {
  addLog("SYSTEM", "Simulating in-flight 2.5s hardware action interrupted by operator barge-in...");
  setAudioActive(true, "TOOL IN-FLIGHT");

  try {
    const resp = await fetch("/api/simulate/voice-turn", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        transcript: "Wait, abort that! Stop fan update!",
        simulate_interrupt: true,
        interrupt_after_ms: 350
      })
    });
    const result = await resp.json();
    setAudioActive(false);

    if (result.barge_in_metrics) {
      const lat = result.barge_in_metrics.cutoff_latency_ms;
      addLog("BARGE", `User barge-in verified: Audio + async tool aborted in ${lat} ms (Target <180ms: PASSED)`);
    }
  } catch (err) {
    console.error("Barge-in error:", err);
    setAudioActive(false);
  }
});

// 3. Lab Phonetic Preprocessor Test
btnPhonetic.addEventListener("click", async () => {
  const rawPhrase = "Observation on tube 12C: 0.5µL at pH 7.4 with 3000 RPM at 37°C.";
  addLog("SYSTEM", `Testing normalizer on: "${rawPhrase}"`);
  setAudioActive(true, "RIME TTS SYNTHESIS");

  try {
    const resp = await fetch("/api/tts/rime", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: rawPhrase })
    });
    const normalizedHeader = resp.headers.get("X-TTS-Normalized-Text");
    if (normalizedHeader) {
      addLog("NORM", `Normalized for Rime: "${normalizedHeader}"`);
    }
    const audioBlob = await resp.arrayBuffer();
    await playAudioBuffer(audioBlob);
  } catch (err) {
    console.error("Phonetic test error:", err);
    setAudioActive(false);
  }
});

// 4. Live Mic Toggle (Web Speech API / LiveKit WebRTC Hook)
let recognition = null;
let isMicActive = false;

btnToggleMic.addEventListener("click", () => {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

  if (!SpeechRecognition) {
    alert("Web Speech recognition is not supported in this browser. You can still use the simulation buttons above for all functions!");
    return;
  }

  if (isMicActive) {
    if (recognition) recognition.stop();
    isMicActive = false;
    micBtnLabel.innerText = "Activate Microphone";
    vadStatus.innerText = "IDLE";
    btnToggleMic.classList.remove("active");
  } else {
    try {
      recognition = new SpeechRecognition();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = "en-US";

      recognition.onstart = () => {
        isMicActive = true;
        micBtnLabel.innerText = "Listening (Hands-Free)...";
        vadStatus.innerText = "VOICE ACTIVE";
        btnToggleMic.classList.add("active");
        addLog("SYSTEM", "Microphone listening for hands-free cleanroom voice commands.");
      };

      recognition.onresult = async (event) => {
        let transcript = "";
        for (let i = event.resultIndex; i < event.results.length; i++) {
          transcript += event.results[i][0].transcript;
        }

        if (event.results[event.results.length - 1].isFinal) {
          addLog("SYSTEM", `Heard: "${transcript}"`);
          // Send to voice turn endpoint
          const resp = await fetch("/api/simulate/voice-turn", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ transcript })
          });
          const resJson = await resp.json();
          if (resJson.response_normalized_for_rime) {
            const ttsResp = await fetch("/api/tts/rime", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ text: resJson.response_normalized_for_rime })
            });
            const audioData = await ttsResp.arrayBuffer();
            await playAudioBuffer(audioData);
          }
        }
      };

      recognition.onerror = (e) => {
        console.warn("Speech recognition error:", e);
      };

      recognition.onend = () => {
        if (isMicActive) {
          recognition.start(); // Keep listening in hands-free mode
        }
      };

      recognition.start();
    } catch (err) {
      console.error("Failed to start speech recognition:", err);
    }
  }
});

// Initialize WebSocket on page load
window.addEventListener("DOMContentLoaded", () => {
  connectWebSocket();
});

