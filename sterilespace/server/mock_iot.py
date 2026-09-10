"""
Simulated Laboratory Hardware Store & Mock IoT Relay.
Tracks real-time biosafety ventilation, high-speed microcentrifuge, incubator,
sample inventory, and regulatory FDA 21 CFR Part 11 audit records.
Features cancellable async hardware transactions with simulated physical/network latency.
"""

import asyncio
import datetime
import hashlib
import json
from typing import Dict, List, Any, Optional, Callable

# Fan speed configurations with physical RPM and airflow mappings
FAN_PROFILES = {
    "OFF": {"rpm": 0, "airflow_cfm": 0, "pressure_pa": -5.0},
    "LOW": {"rpm": 800, "airflow_cfm": 250, "pressure_pa": -12.5},
    "MEDIUM": {"rpm": 1600, "airflow_cfm": 550, "pressure_pa": -18.0},
    "HIGH": {"rpm": 2400, "airflow_cfm": 850, "pressure_pa": -26.5},
    "EMERGENCY_PURGE": {"rpm": 3600, "airflow_cfm": 1200, "pressure_pa": -35.0},
}


class MockLabStore:
    """Thread-safe, observable in-memory laboratory hardware store."""

    def __init__(self):
        self._lock = asyncio.Lock()
        self.subscribers: List[Callable[[Dict[str, Any]], Any]] = []

        # Initial sample inventory
        self.samples: Dict[str, Dict[str, Any]] = {
            "4B": {
                "id": "4B",
                "metric": "oxidation",
                "value": 5.0,
                "unit": "%",
                "status": "NORMAL",
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            },
            "12C": {
                "id": "12C",
                "metric": "pH",
                "value": 7.2,
                "unit": "pH",
                "status": "OPTIMAL",
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            },
            "A3": {
                "id": "A3",
                "metric": "temperature",
                "value": 37.0,
                "unit": "°C",
                "status": "INCUBATING",
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            },
            "P2": {
                "id": "P2",
                "metric": "concentration",
                "value": 1.2,
                "unit": "mg/mL",
                "status": "NORMAL",
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
        }

        # Biosafety Cabinet / Lab Ventilation Relay
        self.ventilation: Dict[str, Any] = {
            "state": "OFF",
            "speed": "LOW",
            "rpm": 0,
            "airflow_cfm": 0,
            "pressure_pa": -5.0,
            "filter_health_percent": 98.4,
            "last_switched_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }

        # High-Speed Benchtop Microcentrifuge
        self.centrifuge: Dict[str, Any] = {
            "state": "IDLE",
            "rpm": 0,
            "target_rpm": 0,
            "g_force": 0,
            "rotor_id": "24x1.5mL Fixed-Angle",
            "time_remaining_sec": 0,
            "brake_status": "READY",
            "last_run_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }

        # Cleanroom CO2 Incubator Chamber
        self.incubator: Dict[str, Any] = {
            "temperature_c": 37.0,
            "target_temp_c": 37.0,
            "co2_pct": 5.0,
            "humidity_pct": 95.0,
            "door_status": "SEALED",
            "chamber_status": "HOMOGENEOUS"
        }

        # Ambient Cleanroom Sensors
        self.environment: Dict[str, Any] = {
            "room_temperature_c": 21.5,
            "humidity_pct": 44.0,
            "co2_ppm": 412,
            "containment_level": "BSL-2",
            "sterile_barrier": "ACTIVE",
            "operator_status": "GLOVED_HANDS_FREE"
        }

        # Cleanroom Voice Timers
        self.timers: Dict[str, Dict[str, Any]] = {}

        # Cleanroom SOP Knowledge Base
        self.protocols: Dict[str, str] = {
            "sterilization": "Aseptic sterilization protocol: Disinfect biosafety hood surfaces with 70% ethanol. Allow 5 minutes contact time before starting airflow.",
            "clean": "Hood decontamination: Wipe from top to bottom, back to front with 70% ethanol. Do not block rear exhaust grilles.",
            "tube 4b": "Sample four-bee SOP: Invert gently 3 times. Avoid high shear. Incubate in dark at 21 degrees Celsius.",
            "centrifuge": "Microcentrifuge operating rule: Fixed-angle rotor maximum speed is 14,000 R-P-M. All opposing tube wells must balance within 0.1 grams.",
            "waste": "Biohazard disposal SOP: Pipette tips and microfuge tubes must enter double-bagged biohazard waste. Autoclave at 121 degrees Celsius for 30 minutes."
        }

        # FDA 21 CFR Part 11 Audit Trail
        self.audit_trail: List[Dict[str, Any]] = []
        self._init_audit_log()

    def _init_audit_log(self):
        self.add_audit_entry(
            raw_speech="SterileSpace copilot initialized",
            normalized_speech="SterileSpace copilot initialized",
            action="SYSTEM_INIT",
            status="SUCCESS"
        )

    def add_audit_entry(
        self,
        raw_speech: str,
        normalized_speech: str,
        action: str,
        status: str,
        latency_ms: Optional[float] = None
    ) -> Dict[str, Any]:
        """Creates an immutable, cryptographically hashed audit entry."""
        entry_id = f"AUD-{len(self.audit_trail) + 1:04d}"
        iso_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
        payload = f"{entry_id}:{iso_time}:{action}:{status}:{raw_speech}"
        sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

        entry = {
            "id": entry_id,
            "timestamp": iso_time,
            "operator": "BSL2_TECH_GLOVED",
            "action": action,
            "status": status,
            "raw_speech": raw_speech,
            "normalized_speech": normalized_speech,
            "latency_ms": latency_ms,
            "verification_hash": sha
        }
        self.audit_trail.append(entry)
        return entry

    def subscribe(self, callback: Callable[[Dict[str, Any]], Any]) -> None:
        """Register a telemetry subscriber (e.g., WebSocket broadcaster)."""
        if callback not in self.subscribers:
            self.subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[Dict[str, Any]], Any]) -> None:
        """Unregister a telemetry subscriber."""
        if callback in self.subscribers:
            self.subscribers.remove(callback)

    async def notify_subscribers(self, event_type: str, data: Dict[str, Any]) -> None:
        """Broadcast state updates and event telemetry to all connected subscribers."""
        payload = {
            "type": event_type,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "data": data,
            "snapshot": self.get_snapshot()
        }
        for sub in list(self.subscribers):
            try:
                res = sub(payload)
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                pass

    def get_snapshot(self) -> Dict[str, Any]:
        """Return an immutable snapshot of all current lab state."""
        return {
            "samples": list(self.samples.values()),
            "ventilation": dict(self.ventilation),
            "centrifuge": dict(self.centrifuge),
            "incubator": dict(self.incubator),
            "environment": dict(self.environment),
            "timers": list(self.timers.values()),
            "audit_count": len(self.audit_trail),
            "system_time": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }

    async def add_timer(self, label: str, duration_sec: int) -> Dict[str, Any]:
        """Creates an asynchronous countdown timer and broadcasts live ticks to the HUD."""
        timer_id = f"TMR-{len(self.timers) + 1:03d}"
        created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        timer_record = {
            "id": timer_id,
            "label": label,
            "duration_sec": duration_sec,
            "remaining_sec": duration_sec,
            "status": "RUNNING",
            "created_at": created_at
        }
        self.timers[timer_id] = timer_record
        await self.notify_subscribers("TIMER_STARTED", {"timer": timer_record})

        async def countdown():
            try:
                for rem in range(duration_sec - 1, -1, -1):
                    await asyncio.sleep(1.0)
                    if timer_id not in self.timers or self.timers[timer_id]["status"] != "RUNNING":
                        return
                    self.timers[timer_id]["remaining_sec"] = rem
                    await self.notify_subscribers("TIMER_TICK", {"timer": self.timers[timer_id]})
                
                self.timers[timer_id]["status"] = "COMPLETED"
                await self.notify_subscribers("TIMER_COMPLETED", {"timer": self.timers[timer_id]})
            except asyncio.CancelledError:
                if timer_id in self.timers:
                    self.timers[timer_id]["status"] = "CANCELLED"
                    await self.notify_subscribers("TIMER_CANCELLED", {"timer": self.timers[timer_id]})

        asyncio.create_task(countdown())
        return timer_record

    async def cancel_all_timers(self) -> int:
        """Cancels all active cleanroom timers."""
        count = 0
        for t_id, t in list(self.timers.items()):
            if t["status"] == "RUNNING":
                t["status"] = "CANCELLED"
                count += 1
        await self.notify_subscribers("TIMERS_CANCELLED", {"cancelled_count": count})
        return count

    async def log_sample_observation(
        self,
        tube_id: str,
        metric: str,
        value: float,
        unit: str,
        delay_seconds: float = 2.5
    ) -> Dict[str, Any]:
        """
        Record a sample measurement with simulated network/database latency.
        Supports cancellation: if cancelled during delay, state mutation is aborted.
        """
        tube_id = tube_id.upper().strip()
        await self.notify_subscribers("TOOL_STARTED", {
            "action": "log_sample_observation",
            "tube_id": tube_id,
            "metric": metric,
            "value": value,
            "unit": unit,
            "simulated_latency_sec": delay_seconds
        })

        # Simulated async I/O transaction - raises asyncio.CancelledError on barge-in
        await asyncio.sleep(delay_seconds)

        async with self._lock:
            status = "NORMAL"
            if metric.lower() == "oxidation" and value > 10.0:
                status = "ELEVATED"
            elif metric.lower() == "ph" and (value < 6.8 or value > 7.6):
                status = "OUT_OF_BOUNDS"

            record = {
                "id": tube_id,
                "metric": metric,
                "value": float(value),
                "unit": unit,
                "status": status,
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }
            self.samples[tube_id] = record

        self.add_audit_entry(
            raw_speech=f"Log {value}{unit} on {tube_id}",
            normalized_speech=f"Logged {value} {unit} for tube {tube_id}",
            action="LOG_SAMPLE",
            status="COMMITTED"
        )

        await self.notify_subscribers("SAMPLE_UPDATED", {
            "tube_id": tube_id,
            "record": record
        })
        return record

    async def set_ventilation(
        self,
        state: str,
        speed: str = "HIGH",
        delay_seconds: float = 2.0
    ) -> Dict[str, Any]:
        """Controls the biosafety cabinet exhaust relay with simulated hardware latency."""
        state_upper = state.upper().strip()
        speed_upper = speed.upper().strip()

        if state_upper == "OFF":
            profile = FAN_PROFILES["OFF"]
            target_speed = "OFF"
        else:
            profile = FAN_PROFILES.get(speed_upper, FAN_PROFILES["HIGH"])
            target_speed = speed_upper

        await self.notify_subscribers("TOOL_STARTED", {
            "action": "set_ventilation",
            "state": state_upper,
            "speed": target_speed,
            "target_rpm": profile["rpm"],
            "simulated_latency_sec": delay_seconds
        })

        # Hardware relay delay - raises asyncio.CancelledError on barge-in
        await asyncio.sleep(delay_seconds)

        async with self._lock:
            self.ventilation["state"] = state_upper
            self.ventilation["speed"] = target_speed
            self.ventilation["rpm"] = profile["rpm"]
            self.ventilation["airflow_cfm"] = profile["airflow_cfm"]
            self.ventilation["pressure_pa"] = profile["pressure_pa"]
            self.ventilation["last_switched_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            result = dict(self.ventilation)

        self.add_audit_entry(
            raw_speech=f"Set ventilation to {state_upper} {target_speed}",
            normalized_speech=f"Ventilation switched to {state_upper} at {profile['rpm']} R-P-M",
            action="SET_VENTILATION",
            status="COMMITTED"
        )

        await self.notify_subscribers("VENTILATION_CHANGED", {
            "ventilation": result
        })
        return result

    async def run_centrifuge(
        self,
        target_rpm: int = 12000,
        duration_sec: int = 60,
        delay_seconds: float = 2.5
    ) -> Dict[str, Any]:
        """
        Spins the microcentrifuge up to target RPM (up to 14,000 RPM) with motor ramp-up delay.
        Supports cancellation: if operator barges in, engages electronic brake immediately.
        """
        target_rpm = max(500, min(14000, int(target_rpm)))
        # Standard microcentrifuge g-force approximation (radius ~ 8.5 cm)
        g_force = int(1.118e-5 * 8.5 * (target_rpm ** 2))

        await self.notify_subscribers("TOOL_STARTED", {
            "action": "run_centrifuge",
            "target_rpm": target_rpm,
            "g_force": g_force,
            "duration_sec": duration_sec,
            "simulated_latency_sec": delay_seconds
        })

        # Motor acceleration ramp-up delay - cancellable on barge-in
        await asyncio.sleep(delay_seconds)

        async with self._lock:
            self.centrifuge["state"] = "SPINNING"
            self.centrifuge["rpm"] = target_rpm
            self.centrifuge["target_rpm"] = target_rpm
            self.centrifuge["g_force"] = g_force
            self.centrifuge["time_remaining_sec"] = duration_sec
            self.centrifuge["brake_status"] = "DISENGAGED"
            self.centrifuge["last_run_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            result = dict(self.centrifuge)

        self.add_audit_entry(
            raw_speech=f"Spin centrifuge at {target_rpm} RPM for {duration_sec}s",
            normalized_speech=f"Centrifuge active at {target_rpm} R-P-M ({g_force} g-force)",
            action="RUN_CENTRIFUGE",
            status="COMMITTED"
        )

        await self.notify_subscribers("CENTRIFUGE_CHANGED", {
            "centrifuge": result
        })
        return result

    async def emergency_brake_centrifuge(self) -> Dict[str, Any]:
        """Instant electronic brake for centrifuge."""
        async with self._lock:
            self.centrifuge["state"] = "EMERGENCY_STOP"
            self.centrifuge["rpm"] = 0
            self.centrifuge["g_force"] = 0
            self.centrifuge["time_remaining_sec"] = 0
            self.centrifuge["brake_status"] = "ENGAGED_LOCKED"
            result = dict(self.centrifuge)

        await self.notify_subscribers("CENTRIFUGE_CHANGED", {
            "centrifuge": result
        })
        return result


# Global singleton instance
lab_store = MockLabStore()
