"""
Simulated Laboratory Hardware Store & Mock IoT Relay.
Tracks real-time biosafety ventilation, sample records, and environmental telemetry.
Features cancellable async hardware transactions with simulated physical/network latency.
"""

import asyncio
import datetime
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

        # Ambient Cleanroom Sensors
        self.environment: Dict[str, Any] = {
            "room_temperature_c": 21.5,
            "humidity_pct": 44.0,
            "co2_ppm": 412,
            "containment_level": "BSL-2",
            "sterile_barrier": "ACTIVE",
            "operator_status": "GLOVED_HANDS_FREE"
        }

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
            except Exception as e:
                # Silently prune or ignore failed subscriber delivery
                pass

    def get_snapshot(self) -> Dict[str, Any]:
        """Return an immutable snapshot of all current lab state."""
        return {
            "samples": list(self.samples.values()),
            "ventilation": dict(self.ventilation),
            "environment": dict(self.environment),
            "system_time": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }

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
        Supports cancellation: if cancelled during the delay, state mutation is aborted.
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
            # Determine threshold warning status
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
        """
        Controls the biosafety cabinet exhaust/fan relay with simulated hardware relay latency.
        Supports cancellation: if cancelled during the delay, fan state remains unmodified.
        """
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

        await self.notify_subscribers("VENTILATION_CHANGED", {
            "ventilation": result
        })
        return result


# Global singleton instance
lab_store = MockLabStore()

