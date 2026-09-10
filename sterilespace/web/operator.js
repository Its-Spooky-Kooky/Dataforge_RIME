/**
 * SterileSpace - 100% Voice-Driven Operator Terminal
 * Pure microphone interaction, Web Audio API RMS noise gating (65 dB hood filter),
 * continuous speech recognition, active incubation timers, and Rime TTS audio synthesis.
 */

// DOM Elements
const btnMicOrb = document.getElementById("btn-mic-orb");
const micIcon = document.getElementById("mic-icon");
const micStateLabel = document.getElementById("mic-state-label");
const micSubtext = document.getElementById("mic-subtext");
const transcriptDisplay = document.getElementById("transcript-display");
const responseDisplay = document.getElementById("response-display");
const ttsAudioTag = document.getElementById("tts-audio-tag");
const wsStatus = document.getElementById("ws-status");
const voiceCanvas = document.getElementById("voice-canvas");
const canvasCtx = voiceCanvas.getContext("2d");

// VU Meter Elements
const vuBarFill = document.getElementById("vu-bar-fill");
const vuDbText = document.getElementById("vu-db-text");

// Timers Section
const timersContainer = document.getElementById("timers-container");
const timersGrid = document.getElementById("timers-grid");

// Web Audio API Context & Nodes
let audioCtx = null;
let analyserNode = null;
let micMediaStream = null;
let isAudioActive = false;
let isRecognizing = false;
let recognition = null;
const NOISE_THRESHOLD_DB = 60; // 60 dB laminar flow hood noise gate

function getAudioContext() {
  if (!audioCtx) {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  }
  if (audioCtx.state === "suspended") {
    audioCtx.resume();
  }
  return audioCtx;
}

// Procedural sound effects
function playCleanroomChime() {
  try {
    const ctx = getAudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(880, ctx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(1320, ctx.currentTime + 0.12);
    gain.gain.setValueAtTime(0.08, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.25);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.25);
  } catch (e) {}
}

function playCutoffClick() {
  try {
    const ctx = getAudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "triangle";
    osc.frequency.setValueAtTime(300, ctx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(50, ctx.currentTime + 0.05);
    gain.gain.setValueAtTime(0.2, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.05);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.05);
  } catch (e) {}
}

// ==============================================================================
// Live Microphone RMS Level & Hood Noise Gating (Web Audio API)
// ==============================================================================
async function initMicrophoneNoiseGating() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    micMediaStream = stream;
    const ctx = getAudioContext();
    const source = ctx.createMediaStreamSource(stream);

    analyserNode = ctx.createAnalyser();
    analyserNode.fftSize = 256;
    source.connect(analyserNode);

    const buffer = new Float32Array(analyserNode.fftSize);

    function updateRMS() {
      if (!analyserNode) return;
      analyserNode.getFloatTimeDomainData(buffer);

      let sum = 0;
      for (let i = 0; i < buffer.length; i++) {
        sum += buffer[i] * buffer[i];
      }
      const rms = Math.sqrt(sum / buffer.length);
      // Approximate dB SPL relative to noise gate
      const db = Math.min(100, Math.max(20, Math.round(20 * Math.log10(rms + 1e-4) + 100)));

      if (vuBarFill && vuDbText) {
        vuBarFill.style.width = `${db}%`;
        if (db > NOISE_THRESHOLD_DB) {
          vuBarFill.style.background = "linear-gradient(90deg, #00e5ff, #00e676)";
          vuDbText.innerText = `${db} dB (VOICE DETECTED)`;
          vuDbText.style.color = "#00e676";
        } else {
          vuBarFill.style.background = "#374151";
          vuDbText.innerText = `${db} dB (HOOD NOISE FILTERED)`;
          vuDbText.style.color = "var(--text-dim)";
        }
      }
      requestAnimationFrame(updateRMS);
    }
    updateRMS();
  } catch (err) {
    if (vuDbText) vuDbText.innerText = "MIC PERMISSION PENDING";
  }
}

// ==============================================================================
// WebSocket Telemetry Connection & Timer Sync
// ==============================================================================
let socket = null;
const activeTimersMap = new Map();

function connectWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws/telemetry`;

  socket = new WebSocket(wsUrl);

  socket.onopen = () => {
    wsStatus.className = "status-pill ws-badge connected";
    wsStatus.innerHTML = '<span class="status-indicator"></span><span>Wall Display Synced</span>';
  };

  socket.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === "TOOL_ABORTED" || msg.type === "BARGE_IN_TRIGGERED") {
        playCutoffClick();
        responseDisplay.innerText = `[ABORT TRIGGERED] Operations halted in ${msg.data.cutoff_latency_ms || 0.1} ms!`;
        responseDisplay.style.color = "#ff5252";
      } else if (msg.type === "TIMER_STARTED" || msg.type === "TIMER_TICK") {
        updateTimerDisplay(msg.data.timer);
      } else if (msg.type === "TIMER_COMPLETED") {
        updateTimerDisplay(msg.data.timer);
        playCleanroomChime();
        responseDisplay.innerText = `[TIMER COMPLETE] ${msg.data.timer.label} countdown finished!`;
        responseDisplay.style.color = "#00e676";
      } else if (msg.type === "TIMERS_CANCELLED") {
        timersGrid.innerHTML = "";
        timersContainer.style.display = "none";
        activeTimersMap.clear();
      }
    } catch (e) {}
  };

  socket.onclose = () => {
    wsStatus.className = "status-pill ws-badge";
    wsStatus.innerHTML = '<span class="status-indicator" style="background:#ff1744"></span><span>Reconnecting...</span>';
    setTimeout(connectWebSocket, 2500);
  };
}

function updateTimerDisplay(timer) {
  if (!timersContainer || !timersGrid) return;
  timersContainer.style.display = "flex";
  activeTimersMap.set(timer.id, timer);

  let existing = document.getElementById(`timer-card-${timer.id}`);
  const isFinished = timer.status === "COMPLETED";

  const cardHtml = `
    <div class="timer-badge-id">${timer.id}</div>
    <div class="timer-body">
      <strong>${timer.label}</strong>
      <span class="timer-countdown ${isFinished ? 'done' : ''}">${timer.remaining_sec}s remaining</span>
    </div>
  `;

  if (existing) {
    existing.innerHTML = cardHtml;
    if (isFinished) existing.classList.add("completed");
  } else {
    const card = document.createElement("div");
    card.id = `timer-card-${timer.id}`;
    card.className = "timer-item";
    card.innerHTML = cardHtml;
    timersGrid.appendChild(card);
  }
}

// ==============================================================================
// Voice Wave Canvas Animation
// ==============================================================================
let wavePhase = 0;

function drawVoiceWave() {
  const w = voiceCanvas.width;
  const h = voiceCanvas.height;
  canvasCtx.clearRect(0, 0, w, h);

  const centerY = h / 2;
  const amp = isAudioActive ? 22 : 3;
  const freq = isAudioActive ? 0.08 : 0.04;

  canvasCtx.lineWidth = 2;
  canvasCtx.strokeStyle = isAudioActive ? "#00e5ff" : "rgba(0, 229, 255, 0.3)";
  canvasCtx.beginPath();

  for (let x = 0; x < w; x++) {
    const y = centerY + Math.sin(x * freq + wavePhase) * amp;
    if (x === 0) canvasCtx.moveTo(x, y);
    else canvasCtx.lineTo(x, y);
  }
  canvasCtx.stroke();

  wavePhase += isAudioActive ? 0.25 : 0.04;
  requestAnimationFrame(drawVoiceWave);
}

drawVoiceWave();

// ==============================================================================
// Audio Playback with Rime TTS
// ==============================================================================
async function playAudioResponse(arrayBuffer) {
  try {
    const ctx = getAudioContext();
    const audioBuffer = await ctx.decodeAudioData(arrayBuffer);
    const source = ctx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(ctx.destination);

    isAudioActive = true;
    ttsAudioTag.innerText = "RIME SPEAKING";
    ttsAudioTag.style.color = "#00e676";
    ttsAudioTag.style.borderColor = "#00e676";

    source.onended = () => {
      isAudioActive = false;
      ttsAudioTag.innerText = "READY";
      ttsAudioTag.style.color = "var(--accent-cyan)";
      ttsAudioTag.style.borderColor = "rgba(0, 229, 255, 0.2)";
    };
    source.start(0);
  } catch (err) {
    isAudioActive = false;
    ttsAudioTag.innerText = "READY";
  }
}

// ==============================================================================
// Execute Laboratory Voice Command
// ==============================================================================
async function executeVoiceCommand(transcript) {
  transcriptDisplay.innerText = `"${transcript}"`;
  responseDisplay.innerText = "Executing command across cleanroom relays...";
  responseDisplay.style.color = "var(--text-primary)";
  isAudioActive = true;

  try {
    const resp = await fetch("/api/simulate/voice-turn", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ transcript })
    });
    const result = await resp.json();

    if (result.status === "INTERRUPTED") {
      playCutoffClick();
      const lat = result.barge_in_metrics ? result.barge_in_metrics.cutoff_latency_ms : 0.1;
      responseDisplay.innerText = `[EMERGENCY ABORT] All hardware actions stopped in ${lat} ms. Rollback verified.`;
      responseDisplay.style.color = "#ff5252";
    } else {
      playCleanroomChime();
      responseDisplay.innerText = `"${result.response_normalized_for_rime || result.response_raw}"`;
      responseDisplay.style.color = "var(--accent-cyan)";

      // Play synthesized Rime speech
      const ttsResp = await fetch("/api/tts/rime", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: result.response_normalized_for_rime })
      });
      const audioData = await ttsResp.arrayBuffer();
      await playAudioResponse(audioData);
    }
  } catch (err) {
    responseDisplay.innerText = "Error contacting laboratory gateway.";
    isAudioActive = false;
  }
}

// ==============================================================================
// Tap-To-Speak Microphone with Silence Auto-Commit & Continuous Speech Recognition
// ==============================================================================
let isMicListening = false;
let speechSilenceTimeout = null;
let lastExecutedCommand = "";

function setupSpeechRecognition() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    if (micSubtext) micSubtext.innerText = "Speech recognition is not natively supported in this browser. Use the voice turn input bar below!";
    return null;
  }

  const rec = new SpeechRecognition();
  rec.continuous = true;
  rec.interimResults = true;
  rec.lang = "en-US";

  rec.onstart = () => {
    isRecognizing = true;
    isMicListening = true;
    if (btnMicOrb) {
      btnMicOrb.classList.add("listening");
      btnMicOrb.classList.remove("tap-ready");
    }
    if (micStateLabel) {
      micStateLabel.innerHTML = '<span class="pulse-dot"></span> LISTENING... SPEAK NOW';
      micStateLabel.style.color = "#00e676";
    }
    if (micSubtext) micSubtext.innerText = "Cleanroom mic live! Speak commands like 'Fan high', 'Centrifuge 12000 RPM', 'Timer 30s'.";
  };

  rec.onresult = (event) => {
    let interimText = "";
    let isFinalFlag = false;

    for (let i = event.resultIndex; i < event.results.length; i++) {
      const text = event.results[i][0].transcript;
      interimText += text;
      if (event.results[i].isFinal) {
        isFinalFlag = true;
      }
    }

    interimText = interimText.trim();
    if (!interimText) return;

    // Show live what the mic is picking up in real time
    if (transcriptDisplay) {
      transcriptDisplay.innerText = `"${interimText}"`;
      transcriptDisplay.style.color = "#00e5ff";
    }
    isAudioActive = true;

    // Clear any existing silence timer
    if (speechSilenceTimeout) {
      clearTimeout(speechSilenceTimeout);
    }

    const triggerCommand = (cmd) => {
      cmd = cmd.trim();
      if (!cmd) return;
      if (cmd.toLowerCase() === lastExecutedCommand.toLowerCase()) return;
      lastExecutedCommand = cmd;
      // Allow repeated commands after 1.8 seconds
      setTimeout(() => { lastExecutedCommand = ""; }, 1800);
      executeVoiceCommand(cmd);
    };

    // If browser flagged isFinal, commit immediately!
    if (isFinalFlag) {
      triggerCommand(interimText);
    } else {
      // Crucial: Auto-commit speech after 750ms of silence even if Chrome didn't set isFinal
      speechSilenceTimeout = setTimeout(() => {
        if (interimText.length > 1) {
          triggerCommand(interimText);
        }
      }, 750);
    }
  };

  rec.onerror = (e) => {
    if (e.error === "not-allowed") {
      if (micSubtext) micSubtext.innerText = "⚠️ Microphone blocked. Click the lock/camera icon in your browser address bar to allow microphone access.";
      stopMicrophone();
    } else if (e.error === "network") {
      if (micSubtext) micSubtext.innerText = "Speech API network notice. Retrying connection...";
      // Auto-restart on network glitch
      setTimeout(() => {
        if (isMicListening) {
          try { rec.start(); } catch (err) {}
        }
      }, 1000);
    } else if (e.error !== "no-speech") {
      console.warn("Speech recognition notice:", e.error);
    }
  };

  rec.onend = () => {
    // Keep continuous listening active while in active speaking state
    if (isRecognizing && isMicListening) {
      try {
        rec.start();
      } catch (e) {}
    }
  };

  return rec;
}

async function startMicrophone() {
  getAudioContext();
  if (!micMediaStream) {
    await initMicrophoneNoiseGating();
  }

  if (!recognition) {
    recognition = setupSpeechRecognition();
  }

  if (recognition) {
    try {
      isRecognizing = true;
      recognition.start();
    } catch (e) {}
  }

  isMicListening = true;
  if (btnMicOrb) {
    btnMicOrb.classList.add("listening");
    btnMicOrb.classList.remove("tap-ready");
  }
  if (micStateLabel) {
    micStateLabel.innerHTML = '<span class="pulse-dot"></span> LISTENING... SPEAK NOW';
    micStateLabel.style.color = "#00e676";
  }
  if (micSubtext) micSubtext.innerText = "Cleanroom mic live! Speak commands like 'Fan high', 'Centrifuge 12000 RPM', 'Timer 30s'. Tap to mute.";
  playCleanroomChime();
}

function stopMicrophone() {
  isRecognizing = false;
  isMicListening = false;
  if (speechSilenceTimeout) {
    clearTimeout(speechSilenceTimeout);
  }
  if (recognition) {
    try {
      recognition.stop();
    } catch (e) {}
  }

  if (btnMicOrb) {
    btnMicOrb.classList.remove("listening");
    btnMicOrb.classList.add("tap-ready");
  }
  if (micStateLabel) {
    micStateLabel.innerText = "TAP TO SPEAK MIC";
    micStateLabel.style.color = "var(--accent-cyan)";
  }
  if (micSubtext) micSubtext.innerText = "Microphone paused. Tap the glowing orb anytime to resume hands-free voice.";
  playCutoffClick();
}

function toggleMicrophone() {
  if (isMicListening) {
    stopMicrophone();
  } else {
    startMicrophone();
  }
}

// Wire up Tap-To-Speak on giant mic orb
if (btnMicOrb) {
  btnMicOrb.addEventListener("click", (e) => {
    e.preventDefault();
    toggleMicrophone();
  });

  btnMicOrb.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      toggleMicrophone();
    }
  });
}

// Wire up Manual Voice Turn Input & Quick Simulation Chips
const manualVoiceInput = document.getElementById("manual-voice-input");
const btnSendVoice = document.getElementById("btn-send-voice");

function sendManualVoiceTurn() {
  if (!manualVoiceInput) return;
  const val = manualVoiceInput.value.trim();
  if (!val) return;
  manualVoiceInput.value = "";
  executeVoiceCommand(val);
}

if (btnSendVoice) {
  btnSendVoice.addEventListener("click", (e) => {
    e.preventDefault();
    sendManualVoiceTurn();
  });
}

if (manualVoiceInput) {
  manualVoiceInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      sendManualVoiceTurn();
    }
  });
}

// Wire up Quick Test Chips
document.querySelectorAll(".voice-chip-btn").forEach((btn) => {
  btn.addEventListener("click", (e) => {
    e.preventDefault();
    const cmd = btn.getAttribute("data-cmd");
    if (cmd) {
      executeVoiceCommand(cmd);
    }
  });
});

window.addEventListener("DOMContentLoaded", () => {
  connectWebSocket();
  if (btnMicOrb) btnMicOrb.classList.add("tap-ready");
});
