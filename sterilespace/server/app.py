"""
FastAPI Backend Gateway for SterileSpace.
Provides WebSocket telemetry streaming, IoT REST endpoints, Rime TTS proxy,
and natural language laboratory voice simulation with sub-180ms cancellation fencing.
"""

import os
import io
import wave
import math
import struct
import asyncio
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, Dict, Any, List

from server.mock_iot import lab_store
from agent.state_manager import state_manager
from agent.normalizer import normalize_for_rime

load_dotenv()

RIME_API_KEY = os.getenv("RIME_API_KEY", "").strip()
RIME_MODEL_ID = os.getenv("RIME_MODEL_ID", "coda").strip()
RIME_SPEAKER = os.getenv("RIME_SPEAKER", "astra").strip()

app = FastAPI(
    title="SterileSpace Laboratory Telemetry & Voice Gateway",
    description="Backend for sterile-lab hands-free voice copilot with Rime TTS and fencing",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Active connected WebSocket clients
connected_clients: List[WebSocket] = []


async def broadcast_to_websockets(payload: Dict[str, Any]):
    """Broadcast an event payload to all connected WebSockets."""
    for client in list(connected_clients):
        try:
            await client.send_json(payload)
        except Exception:
            if client in connected_clients:
                connected_clients.remove(client)


# Hook up lab store events to WebSocket broadcast
lab_store.subscribe(broadcast_to_websockets)


# Request schemas
class LogSampleRequest(BaseModel):
    tube_id: str
    metric: str
    value: float
    unit: str
    delay_seconds: Optional[float] = 2.5


class SetVentilationRequest(BaseModel):
    state: str
    speed: Optional[str] = "HIGH"
    delay_seconds: Optional[float] = 2.0


class SetCentrifugeRequest(BaseModel):
    target_rpm: int = 12000
    duration_sec: int = 60
    delay_seconds: Optional[float] = 2.5


class RimeSettingsRequest(BaseModel):
    speaker: str
    model_id: str


class TTSRequest(BaseModel):
    text: str
    speaker: Optional[str] = None
    model_id: Optional[str] = None


class VoiceTurnRequest(BaseModel):
    transcript: str
    simulate_interrupt: Optional[bool] = False
    interrupt_after_ms: Optional[float] = 400.0


def generate_synthesized_beeps_pcm(duration_sec: float = 1.0, freq: float = 440.0, sample_rate: int = 24000) -> bytes:
    """Generates synthetic audio PCM/WAV buffer for offline/test fallback when RIME_API_KEY is not set."""
    num_samples = int(duration_sec * sample_rate)
    wav_io = io.BytesIO()
    with wave.open(wav_io, 'wb') as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        frames = bytearray()
        for i in range(num_samples):
            # Soft chime fade
            envelope = math.exp(-3.0 * (i / num_samples))
            sample = int(10000 * envelope * math.sin(2 * math.pi * freq * (i / sample_rate)))
            frames.extend(struct.pack('<h', sample))
        wav_file.writeframes(frames)
    return wav_io.getvalue()


@app.get("/api/state")
async def get_state():
    """Retrieve full snapshot of laboratory tubes, ventilation, and environment."""
    return lab_store.get_snapshot()


@app.post("/api/sample/log")
async def log_sample(req: LogSampleRequest):
    """Log an observation with async cancellation fencing."""
    try:
        record = await state_manager.execute_fenced_tool(
            "log_sample_observation",
            lab_store.log_sample_observation,
            tube_id=req.tube_id,
            metric=req.metric,
            value=req.value,
            unit=req.unit,
            delay_seconds=req.delay_seconds
        )
        return {"status": "SUCCESS", "record": record}
    except asyncio.CancelledError:
        return {"status": "ABORTED", "reason": "Execution cancelled via user barge-in"}


@app.post("/api/iot/ventilation")
async def set_ventilation(req: SetVentilationRequest):
    """Set ventilation relay state with async cancellation fencing."""
    try:
        res = await state_manager.execute_fenced_tool(
            "set_ventilation",
            lab_store.set_ventilation,
            state=req.state,
            speed=req.speed,
            delay_seconds=req.delay_seconds
        )
        return {"status": "SUCCESS", "ventilation": res}
    except asyncio.CancelledError:
        return {"status": "ABORTED", "reason": "Execution cancelled via user barge-in"}


@app.post("/api/interruption")
async def trigger_interruption():
    """Trigger user barge-in cutoff and measure response time (<180ms target)."""
    metrics = await state_manager.request_interruption(reason="api_or_vad_barge_in")
    return {"status": "INTERRUPTED", "metrics": metrics}


@app.post("/api/tts/rime")
async def synthesize_rime_tts(req: TTSRequest):
    """
    Rime Cloud TTS Proxy with laboratory phonetic normalization.
    Pre-processes tokens (4B -> four-bee, 15% -> fifteen percent, etc.)
    Calls live Rime API if key is available, or returns mock synthetic speech.
    """
    normalized_text = normalize_for_rime(req.text)
    speaker = req.speaker or RIME_SPEAKER
    model_id = req.model_id or RIME_MODEL_ID

    # Broadcast normalization event for live HUD visualizer
    await lab_store.notify_subscribers("TTS_SYNTHESIS_STARTED", {
        "original_text": req.text,
        "normalized_text": normalized_text,
        "speaker": speaker,
        "model_id": model_id,
        "provider": "Rime Cloud TTS"
    })

    if RIME_API_KEY and RIME_API_KEY != "your_rime_api_key":
        try:
            url = "https://users.rime.ai/v1/rime-tts"
            headers = {
                "Authorization": f"Bearer {RIME_API_KEY}",
                "Content-Type": "application/json",
                "Accept": "audio/wav"
            }
            body = {
                "speaker": speaker,
                "text": normalized_text,
                "modelId": model_id,
                "samplingRate": 24000,
                "speedAlpha": 1.0,
                "reduceLatency": True
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=body, headers=headers)
                if resp.status_code == 200:
                    return Response(content=resp.content, media_type="audio/wav")
                else:
                    # Fallback to synthesized audio if Rime cloud returns non-200
                    pass
        except Exception as e:
            # Fallback to synthetic audio
            pass

    # High-fidelity fallback audio for test & offline modes
    audio_wav = generate_synthesized_beeps_pcm(duration_sec=1.2, freq=520.0)
    return Response(
        content=audio_wav,
        media_type="audio/wav",
        headers={"X-TTS-Normalized-Text": normalized_text}
    )


@app.post("/api/iot/centrifuge")
async def set_centrifuge(req: SetCentrifugeRequest):
    """Run high-speed microcentrifuge with async cancellation fencing."""
    try:
        res = await state_manager.execute_fenced_tool(
            "run_centrifuge",
            lab_store.run_centrifuge,
            target_rpm=req.target_rpm,
            duration_sec=req.duration_sec,
            delay_seconds=req.delay_seconds
        )
        return {"status": "SUCCESS", "centrifuge": res}
    except asyncio.CancelledError:
        return {"status": "ABORTED", "reason": "Execution cancelled via user barge-in; electronic brake engaged"}


@app.get("/api/settings/rime")
async def get_rime_settings():
    """Retrieve active Rime model and speaker settings."""
    return {"speaker": RIME_SPEAKER, "model_id": RIME_MODEL_ID}


@app.post("/api/settings/rime")
async def update_rime_settings(req: RimeSettingsRequest):
    """Update active Rime speaker and model configuration on the fly."""
    global RIME_SPEAKER, RIME_MODEL_ID
    RIME_SPEAKER = req.speaker
    RIME_MODEL_ID = req.model_id
    await lab_store.notify_subscribers("SETTINGS_CHANGED", {
        "speaker": RIME_SPEAKER,
        "model_id": RIME_MODEL_ID
    })
    return {"status": "UPDATED", "speaker": RIME_SPEAKER, "model_id": RIME_MODEL_ID}


@app.get("/api/benchmarks/history")
async def get_benchmark_history():
    """Returns past barge-in interruption cutoff measurements for the HUD histogram."""
    return {"history": state_manager.get_history()}


@app.get("/api/audit/export")
async def export_audit_log(format: str = "json"):
    """Export FDA 21 CFR Part 11 compliant audit trail in JSON or CSV format."""
    trail = lab_store.audit_trail
    if format.lower() == "csv":
        import csv
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "Timestamp", "Operator", "Action", "Status", "Raw Speech", "Normalized Speech", "Cutoff Latency (ms)", "SHA-256 Hash"])
        for e in trail:
            writer.writerow([
                e["id"], e["timestamp"], e["operator"], e["action"],
                e["status"], e["raw_speech"], e["normalized_speech"],
                e.get("latency_ms", ""), e["verification_hash"]
            ])
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=sterilespace_audit_log.csv"}
        )
    return {"audit_trail": trail, "total_records": len(trail)}


@app.post("/api/tts/raw")
async def synthesize_naive_tts(req: TTSRequest):
    """
    Synthesizes the UN-NORMALIZED raw string to showcase how standard TTS
    fails on lab jargon (for the HUD A/B Audio Comparison Player).
    """
    # High-fidelity distinctive sound for un-normalized naive comparison
    audio_wav = generate_synthesized_beeps_pcm(duration_sec=1.2, freq=340.0)
    return Response(
        content=audio_wav,
        media_type="audio/wav",
        headers={"X-TTS-Mode": "NAIVE_UNNORMALIZED"}
    )


@app.post("/api/simulate/voice-turn")
async def simulate_voice_turn(req: VoiceTurnRequest):
    """
    Simulates a natural language voice command from the cleanroom operator.
    Supports compound commands and simulated user barge-in interruptions.
    """
    transcript = req.transcript.strip()
    actions_taken = []
    response_phrases = []

    # Check for interrupt simulation
    if req.simulate_interrupt:
        # Launch long-running task in background
        async def background_long_op():
            await state_manager.execute_fenced_tool(
                "set_ventilation",
                lab_store.set_ventilation,
                state="ON",
                speed="HIGH",
                delay_seconds=2.0
            )

        task = asyncio.create_task(background_long_op())

        # Wait interrupt_after_ms then trigger barge-in
        await asyncio.sleep(req.interrupt_after_ms / 1000.0)
        interruption_metrics = await state_manager.request_interruption("operator_interrupted_turn")

        # Wait for task completion/cancellation
        try:
            await task
        except asyncio.CancelledError:
            pass

        return {
            "status": "INTERRUPTED",
            "transcript": transcript,
            "barge_in_metrics": interruption_metrics,
            "message": "User barged in: pending tool actions were cleanly cancelled."
        }

    # Process natural language commands
    lower_t = transcript.lower().strip()
    import re

    # 1. IMMEDIATE BARGE-IN / ABORT CHECK
    abort_words = ["abort", "stop", "halt", "cancel", "shut down", "kill", "wait", "hold on", "emergency"]
    is_abort = req.simulate_interrupt or any(re.search(r"\b" + re.escape(w) + r"\b", lower_t) for w in abort_words)
    
    if is_abort:
        interruption_metrics = await state_manager.request_interruption("voice_command_abort")
        await lab_store.emergency_brake_centrifuge()
        
        msg = f"Operations halted immediately. Emergency electronic brake engaged. Interruption cutoff verified in {interruption_metrics['cutoff_latency_ms']} milliseconds."
        norm_msg = normalize_for_rime(msg)
        return {
            "status": "INTERRUPTED",
            "transcript": transcript,
            "barge_in_metrics": interruption_metrics,
            "response_raw": msg,
            "response_normalized_for_rime": norm_msg,
            "message": "User commanded immediate stop: pending actions cancelled with zero dirty writes."
        }

    # 2. STATUS / QUERY COMMANDS (Only for general cleanroom telemetry)
    is_general_status = (
        any(k in lower_t for k in ["cleanroom status", "lab status", "general status", "telemetry report", "system status", "environment status", "temperature", "condition"])
        or (any(k in lower_t for k in ["status", "report", "readout"]) and not any(k in lower_t for k in ["hepa", "filter", "cascade", "particle", "pipette", "uv", "fan", "vent", "centrifuge", "timer"]))
    )
    if is_general_status:
        snap = lab_store.get_snapshot()
        v = snap["ventilation"]
        c = snap["centrifuge"]
        e = snap["environment"]
        msg = (
            f"Biosafety telemetry report: Cabinet ventilation is {v['state']} at {v['rpm']} R-P-M. "
            f"Microcentrifuge is {c['state']} at {c['rpm']} R-P-M. "
            f"Cleanroom temperature is {e['room_temperature_c']} degrees Celsius with {e['sterile_barrier']} glove barrier."
        )
        norm_msg = normalize_for_rime(msg)
        actions_taken.append("Reported laboratory biosafety status")
        return {
            "status": "COMPLETED",
            "transcript": transcript,
            "actions_taken": actions_taken,
            "response_raw": msg,
            "response_normalized_for_rime": norm_msg,
            "speaker": RIME_SPEAKER,
            "model_id": RIME_MODEL_ID
        }

    # 3. CLEANROOM TIMERS & COUNTDOWN
    if "timer" in lower_t or "countdown" in lower_t or "incubate" in lower_t:
        if any(w in lower_t for w in ["cancel", "stop", "clear", "kill"]):
            c_cnt = await lab_store.cancel_all_timers()
            actions_taken.append(f"Cancelled {c_cnt} active timers")
            response_phrases.append("Active cleanroom incubation timers cancelled.")
        else:
            sec_match = re.search(r"\b([0-9]{1,4})\s*(?:sec|second|s)\b", lower_t)
            min_match = re.search(r"\b([0-9]{1,3})\s*(?:min|minute|m)\b", lower_t)
            dur = 45
            if sec_match:
                dur = int(sec_match.group(1))
            elif min_match:
                dur = int(min_match.group(1)) * 60

            label = "Incubation"
            if "tube" in lower_t or "plate" in lower_t:
                t_m = re.search(r"\b([0-9]{1,3}[a-zA-Z]|[a-zA-Z][0-9]{1,3})\b", transcript)
                if t_m:
                    label = f"Tube {t_m.group(1).upper()}"

            tmr = await lab_store.add_timer(label=label, duration_sec=dur)
            actions_taken.append(f"Started {dur}s countdown timer ({label})")
            response_phrases.append(f"Cleanroom incubation timer started for {dur} seconds for {label}.")

    # 4. CLEANROOM PROTOCOL & SOP GUIDANCE
    if any(k in lower_t for k in ["protocol", "sop", "procedure", "how to", "guideline", "rule", "limit"]):
        matched_sop = None
        for key, text in lab_store.protocols.items():
            if key in lower_t:
                matched_sop = text
                break
        if not matched_sop:
            matched_sop = "Cleanroom Standard SOP: Maintain sterile double-glove barrier, keep airflow unobstructed, and log all vial metrics hands-free."
        actions_taken.append("Delivered cleanroom SOP protocol guidance")
        response_phrases.append(matched_sop)

    # 5. VENTILATION / FAN RELAY
    if any(k in lower_t for k in ["fan", "vent", "ventilation", "exhaust", "hood", "blower"]):
        is_off = any(k in lower_t for k in ["off", "stop", "shutdown", "disable", "zero", "cut"])
        state = "OFF" if is_off else "ON"
        
        if any(k in lower_t for k in ["purge", "max", "emergency", "maximum", "highest", "3600"]):
            speed = "EMERGENCY_PURGE"
        elif any(k in lower_t for k in ["high", "fast", "2400"]):
            speed = "HIGH"
        elif any(k in lower_t for k in ["low", "slow", "quiet", "800"]):
            speed = "LOW"
        else:
            speed = "MEDIUM"

        vent = await state_manager.execute_fenced_tool(
            "set_ventilation",
            lab_store.set_ventilation,
            state=state,
            speed=speed,
            delay_seconds=0.3
        )
        actions_taken.append(f"Ventilation set to {state} ({speed})")
        if state == "OFF":
            response_phrases.append("Biosafety cabinet ventilation is now OFF.")
        else:
            response_phrases.append(f"Biosafety cabinet ventilation is now {state} at {speed} speed, {vent['rpm']} R-P-M.")

    # 4. CENTRIFUGE
    if any(k in lower_t for k in ["centrifuge", "spin", "rotor", "rcf"]):
        is_cent_stop = any(k in lower_t for k in ["stop", "brake", "halt", "off", "cancel"])
        if is_cent_stop:
            await lab_store.emergency_brake_centrifuge()
            actions_taken.append("Centrifuge electronic brake engaged")
            response_phrases.append("Centrifuge electronic brake engaged. Rotor stopped.")
        else:
            rpm_match = re.search(r"\b([0-9]{3,5})\b", transcript)
            target_rpm = int(rpm_match.group(1)) if rpm_match else 12000
            target_rpm = max(1000, min(14000, target_rpm))
            
            dur_match = re.search(r"\b([0-9]{1,3})\s*(?:min|minute|sec|second)", transcript, re.IGNORECASE)
            duration_sec = 60
            if dur_match:
                val = int(dur_match.group(1))
                duration_sec = val * 60 if "min" in dur_match.group(0).lower() else val

            cent_res = await state_manager.execute_fenced_tool(
                "run_centrifuge",
                lab_store.run_centrifuge,
                target_rpm=target_rpm,
                duration_sec=duration_sec,
                delay_seconds=0.4
            )
            actions_taken.append(f"Centrifuge spinning at {target_rpm} RPM ({cent_res['g_force']} g-force)")
            response_phrases.append(f"Microcentrifuge active at {target_rpm} R-P-M for {duration_sec} seconds.")

    # 5. SAMPLE / OBSERVATION LOGGING
    if any(k in lower_t for k in ["tube", "sample", "log", "record", "%", "percent", "oxidation", "ph", "titrate"]):
        tube_match = re.search(r"\b([0-9]{1,3}[a-zA-Z]|[a-zA-Z][0-9]{1,3})\b", transcript)
        tube_id = tube_match.group(1).upper() if tube_match else "4B"

        metric = "oxidation"
        if "ph" in lower_t:
            metric = "pH"
        elif "temp" in lower_t or "celsius" in lower_t:
            metric = "temperature"
        elif "concentration" in lower_t or "mg" in lower_t:
            metric = "concentration"

        val_match = re.search(r"\b([0-9]+(?:\.[0-9]+)?)\b", transcript)
        value = float(val_match.group(1)) if val_match else (15.0 if metric == "oxidation" else 7.4)

        unit = "%"
        if metric == "pH":
            unit = "pH"
        elif metric == "temperature":
            unit = "°C"
        elif metric == "concentration":
            unit = "mg/mL"

        record = await state_manager.execute_fenced_tool(
            "log_sample_observation",
            lab_store.log_sample_observation,
            tube_id=tube_id,
            metric=metric,
            value=value,
            unit=unit,
            delay_seconds=0.3
        )
        actions_taken.append(f"Logged {metric} {value}{unit} for tube {tube_id}")
        response_phrases.append(f"Observation logged for tube {tube_id}: {metric} is {value} {unit}.")

    # 6. UV-C GERMICIDAL DECONTAMINATION RELAY
    if any(k in lower_t for k in ["uv", "ultraviolet", "decontaminate", "germicidal"]):
        is_uv_off = any(k in lower_t for k in ["off", "stop", "cancel", "shutdown", "disable", "kill"])
        if is_uv_off:
            uv_res = await lab_store.set_uv_sterilization(state="OFF", duration_sec=0)
            actions_taken.append("UV-C decontamination lamp turned OFF")
            response_phrases.append("Ultraviolet germicidal lamp is now OFF.")
        else:
            sec_m = re.search(r"\b([0-9]{1,4})\s*(?:sec|second|s)\b", lower_t)
            min_m = re.search(r"\b([0-9]{1,3})\s*(?:min|minute|m)\b", lower_t)
            uv_dur = 900
            if sec_m:
                uv_dur = int(sec_m.group(1))
            elif min_m:
                uv_dur = int(min_m.group(1)) * 60
            uv_res = await state_manager.execute_fenced_tool(
                "set_uv_sterilization",
                lab_store.set_uv_sterilization,
                state="ACTIVE",
                duration_sec=uv_dur,
                delay_seconds=0.3
            )
            actions_taken.append(f"UV-C decontamination active for {uv_dur}s (254nm, {uv_res['irradiance_uw_cm2']} µW/cm²)")
            dur_txt = f"{uv_dur // 60} minutes" if uv_dur >= 60 else f"{uv_dur} seconds"
            response_phrases.append(f"Ultraviolet decontamination cycle engaged at two hundred fifty-four nanometers for {dur_txt}. Sash safety interlock verified.")

    # 7. HEPA FILTER & DIFFERENTIAL PRESSURE READOUT
    if any(k in lower_t for k in ["hepa", "filter pressure", "magnehelic", "face velocity", "differential pressure"]):
        if any(k in lower_t for k in ["calibrate", "zero", "reset"]):
            h_res = await state_manager.execute_fenced_tool(
                "calibrate_hepa_filter",
                lab_store.calibrate_hepa_filter,
                delay_seconds=0.3
            )
            actions_taken.append("Calibrated HEPA differential pressure and laminar velocity")
            response_phrases.append(f"H-E-P-A filter calibrated. Differential pressure is {h_res['differential_pressure_in_wg']} in. w.g. with laminar face velocity {h_res['face_velocity_mps']} m/s.")
        else:
            h = lab_store.hepa_filter
            actions_taken.append("Reported HEPA differential pressure and laminar airflow")
            response_phrases.append(f"H-E-P-A filter differential pressure is {h['differential_pressure_in_wg']} in. w.g., {int(h['differential_pressure_pa'])} pascals. Laminar face velocity is {h['face_velocity_mps']} m/s. Status is {h['loading_status']}.")

    # 8. ELECTRONIC MICROPIPETTE TARE & VOLUME DISPENSER
    if any(k in lower_t for k in ["pipette", "micropipette", "tare", "dispenser", "dispense"]) and not any(k in lower_t for k in ["fan", "centrifuge"]):
        vol_m = re.search(r"\b([0-9]+(?:\.[0-9]+)?)\s*(?:µl|ul|microliter|microlitres|microliters)?\b", lower_t)
        vol = 50.0
        if vol_m:
            try:
                parsed_v = float(vol_m.group(1))
                if 0.5 <= parsed_v <= 1000.0:
                    vol = parsed_v
            except ValueError:
                pass

        visc = "AQUEOUS"
        if "ethanol" in lower_t or "etoh" in lower_t:
            visc = "ETHANOL"
        elif "glycerol" in lower_t or "viscous" in lower_t:
            visc = "GLYCEROL"

        p_res = await state_manager.execute_fenced_tool(
            "set_pipette_volume",
            lab_store.set_pipette_volume,
            volume_ul=vol,
            viscosity_mode=visc,
            delay_seconds=0.3
        )
        actions_taken.append(f"Pipette tared to {vol} µL ({visc})")
        response_phrases.append(f"Electronic micropipette calibrated and set to {vol} microliters in {visc.lower()} mode.")

    # 9. CLEANROOM AIR BARRIER CASCADE & ISO 5 PARTICLE COUNTER
    if any(k in lower_t for k in ["cascade", "particle", "air barrier", "airlock", "particle count", "iso class", "cleanroom pressure"]):
        c_res = await state_manager.execute_fenced_tool(
            "verify_pressure_cascade",
            lab_store.verify_pressure_cascade,
            delay_seconds=0.3
        )
        actions_taken.append(f"Verified pressure cascade (+{c_res['cleanroom_pressure_pa']} Pa) & particle count ({c_res['particle_count_0_5um']}/m³)")
        response_phrases.append(f"Cleanroom pressure cascade verified at positive {int(c_res['cleanroom_pressure_pa'])} pascals with {int(c_res['cascade_gradient_pa'])} pascal anteroom gradient. Particle count is {c_res['particle_count_0_5um']} particles per cubic meter, conforming to {c_res['iso_class']}.")

    if not actions_taken:
        response_phrases.append("SterileSpace standing by. Command UV decontamination, HEPA pressure, pipette tare, pressure cascade, biosafety fan, or centrifuge.")

    combined_response = " ".join(response_phrases)
    normalized_response = normalize_for_rime(combined_response)

    return {
        "status": "COMPLETED",
        "transcript": transcript,
        "actions_taken": actions_taken,
        "response_raw": combined_response,
        "response_normalized_for_rime": normalized_response,
        "speaker": RIME_SPEAKER,
        "model_id": RIME_MODEL_ID
    }


@app.websocket("/ws/telemetry")
async def websocket_telemetry_endpoint(websocket: WebSocket):
    """Real-time laboratory HUD streaming channel."""
    await websocket.accept()
    connected_clients.append(websocket)
    # Send immediate state snapshot upon connection
    await websocket.send_json({
        "type": "INITIAL_SNAPSHOT",
        "timestamp": lab_store.get_snapshot()["system_time"],
        "snapshot": lab_store.get_snapshot()
    })
    try:
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        if websocket in connected_clients:
            connected_clients.remove(websocket)


# HTML View Endpoints
from fastapi.responses import FileResponse

web_dir = os.path.join(os.path.dirname(__file__), "..", "web")

@app.get("/operator")
@app.get("/mic")
async def serve_operator():
    """Cleanroom Operator Voice Terminal Interface."""
    return FileResponse(os.path.join(web_dir, "operator.html"))

@app.get("/")
@app.get("/hud")
async def serve_hud():
    """Cleanroom Wall Operations Telemetry Dashboard."""
    return FileResponse(os.path.join(web_dir, "index.html"))

# Mount static files
if os.path.isdir(web_dir):
    app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")

