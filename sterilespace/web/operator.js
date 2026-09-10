/**
 * SterileSpace - Cleanroom Operator Voice Terminal Client
 * Continuous hands-free voice recognition, giant pulsing mic orb,
 * audio playback with Rime TTS, quick command chips, and real-time WebSocket link.
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

// Audio Context & Analyser
let audioCtx = null;
let analyser = null;
let isAudioActive = false;

function getAudioContext() {
  if (!audioCtx) {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 64;
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
// WebSocket Telemetry Connection
// ==============================================================================
let socket = null;

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
        responseDisplay.innerText = `[ABORT TRIGGERED] Operations immediately halted in ${msg.data.cutoff_latency_ms || 0.1} ms!`;
        responseDisplay.style.color = "#ff5252";
      } else if (msg.type === "SAMPLE_UPDATED") {
        playCleanroomChime();
      }
    } catch (e) {}
  };

  socket.onclose = () => {
    wsStatus.className = "status-pill ws-badge";
    wsStatus.innerHTML = '<span class="status-indicator" style="background:#ff1744"></span><span>Reconnecting...</span>';
    setTimeout(connectWebSocket, 2500);
  };
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
// Web Speech Recognition (Hands-Free Listening)
// ==============================================================================
let recognition = null;
let isListening = false;

function initSpeechRecognition() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    micSubtext.innerText = "Web Speech not supported in this browser. Use the Quick Command Chips below!";
    return;
  }

  recognition = new SpeechRecognition();
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.lang = "en-US";

  recognition.onstart = () => {
    isListening = true;
    btnMicOrb.classList.add("listening");
    micIcon.innerText = "🎙️";
    micStateLabel.innerText = "LISTENING (HANDS-FREE ACTIVE)";
    micStateLabel.style.color = "#00e676";
    micSubtext.innerText = "Speak any command: 'Set fan high', 'Spin centrifuge 12000', or 'Stop'!";
  };

  recognition.onresult = (event) => {
    let interimTranscript = "";
    let finalTranscript = "";

    for (let i = event.resultIndex; i < event.results.length; i++) {
      const trans = event.results[i][0].transcript;
      if (event.results[i].isFinal) {
        finalTranscript += trans;
      } else {
        interimTranscript += trans;
      }
    }

    if (interimTranscript) {
      transcriptDisplay.innerText = `"...${interimTranscript}"`;
    }

    if (finalTranscript) {
      executeVoiceCommand(finalTranscript.trim());
    }
  };

  recognition.onerror = (e) => {
    if (e.error !== "no-speech") {
      console.warn("Speech error:", e.error);
    }
  };

  recognition.onend = () => {
    // Keep continuous listening active in cleanroom mode
    if (isListening) {
      try {
        recognition.start();
      } catch (e) {}
    } else {
      btnMicOrb.classList.remove("listening");
      micStateLabel.innerText = "TAP TO ACTIVATE HANDS-FREE MIC";
      micStateLabel.style.color = "var(--text-primary)";
    }
  };
}

// Toggle Mic Button Click
btnMicOrb.addEventListener("click", () => {
  getAudioContext();
  if (!recognition) {
    initSpeechRecognition();
  }

  if (isListening) {
    isListening = false;
    if (recognition) recognition.stop();
    btnMicOrb.classList.remove("listening");
    micStateLabel.innerText = "MIC PAUSED - TAP TO RESUME";
    micStateLabel.style.color = "var(--text-muted)";
  } else {
    isListening = true;
    try {
      recognition.start();
    } catch (e) {}
  }
});

// ==============================================================================
// Quick Command Chips & Emergency Abort Button
// ==============================================================================
document.querySelectorAll(".voice-chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    const cmd = chip.getAttribute("data-command");
    executeVoiceCommand(cmd);
  });
});

window.addEventListener("DOMContentLoaded", () => {
  connectWebSocket();
  initSpeechRecognition();
});
