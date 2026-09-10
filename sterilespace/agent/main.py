"""
SterileSpace LiveKit Agent Worker with Rime TTS & Tool Fencing.
Hands-free voice copilot for cleanroom and biosafety laboratories.
"""

import os
import sys
import asyncio
import logging
from typing import Annotated
from dotenv import load_dotenv

# Ensure sterilespace root is available in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from agent.normalizer import normalize_for_rime
    from agent.state_manager import state_manager
    from server.mock_iot import lab_store
except ImportError:
    from sterilespace.agent.normalizer import normalize_for_rime
    from sterilespace.agent.state_manager import state_manager
    from sterilespace.server.mock_iot import lab_store

load_dotenv()

logger = logging.getLogger("sterilespace-agent")
logging.basicConfig(level=logging.INFO)

RIME_API_KEY = os.getenv("RIME_API_KEY", "")
RIME_MODEL_ID = os.getenv("RIME_MODEL_ID", "coda")
RIME_SPEAKER = os.getenv("RIME_SPEAKER", "astra")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
LIVEKIT_URL = os.getenv("LIVEKIT_URL", "")


class LabAssistantTools:
    """
    Exposes laboratory function calling tools to the LLM agent.
    Each tool is fenced inside state_manager to allow sub-180ms cancellation upon barge-in.
    """

    def __init__(self):
        self.name = "LabAssistantTools"

    async def log_sample_observation(
        self,
        tube_id: Annotated[str, "Alphanumeric tube or plate label, e.g., 4B, 12C, A3"],
        metric: Annotated[str, "Measured parameter such as oxidation, pH, concentration"],
        value: Annotated[float, "Numerical value of observation"],
        unit: Annotated[str, "Measurement unit, e.g., %, pH, microliters, mg/mL"]
    ) -> str:
        """Records a sample observation into the laboratory inventory store with simulated 2.5s latency."""
        try:
            record = await state_manager.execute_fenced_tool(
                "log_sample_observation",
                lab_store.log_sample_observation,
                tube_id=tube_id,
                metric=metric,
                value=value,
                unit=unit,
                delay_seconds=2.5
            )
            # Pre-normalize the confirmation phrase for Rime TTS
            msg = f"Logged observation for tube {tube_id}: {metric} is {value} {unit}."
            return normalize_for_rime(msg)
        except asyncio.CancelledError:
            return "Observation logging was cancelled due to operator barge-in."

    async def set_ventilation(
        self,
        state: Annotated[str, "Ventilation state: ON or OFF"],
        speed: Annotated[str, "Fan speed profile: LOW, MEDIUM, HIGH, or EMERGENCY_PURGE"] = "HIGH"
    ) -> str:
        """Adjusts biosafety cabinet exhaust relay with simulated 2.0s hardware latency."""
        try:
            res = await state_manager.execute_fenced_tool(
                "set_ventilation",
                lab_store.set_ventilation,
                state=state,
                speed=speed,
                delay_seconds=2.0
            )
            msg = f"Ventilation is now {state} at {speed} speed with {res['rpm']} R-P-M."
            return normalize_for_rime(msg)
        except asyncio.CancelledError:
            return "Ventilation change was aborted due to operator barge-in."

    async def get_biosafety_status(self) -> str:
        """Retrieves immediate ambient cleanroom sensor and cabinet status."""
        snap = lab_store.get_snapshot()
        vent = snap["ventilation"]
        env = snap["environment"]
        msg = (
            f"Biosafety cabinet ventilation is {vent['state']} at {vent['rpm']} R-P-M. "
            f"Room temperature is {env['room_temperature_c']} degrees Celsius. "
            f"Containment barrier is {env['sterile_barrier']}."
        )
        return normalize_for_rime(msg)


def setup_livekit_pipeline():
    """
    Configures and returns the LiveKit VoicePipelineAgent with Rime TTS and Silero VAD.
    """
    try:
        from livekit.agents import JobContext, WorkerOptions, cli
        from livekit.agents.pipeline import VoicePipelineAgent
        from livekit.plugins import silero, openai
        import livekit.plugins.rime as rime

        tools = LabAssistantTools()

        async def entrypoint(ctx: JobContext):
            logger.info("Connecting to LiveKit room: %s", ctx.room.name)
            await ctx.connect()

            # Initialize Rime TTS with selected speaker and model
            tts_plugin = rime.TTS(
                model=RIME_MODEL_ID,
                speaker=RIME_SPEAKER,
                reduce_latency=True
            )

            # Silero Voice Activity Detector for low-latency barge-in
            vad_plugin = silero.VAD.load()

            # OpenAI LLM for function calling
            llm_plugin = openai.LLM(
                model="gpt-4o-mini"
            )

            agent = VoicePipelineAgent(
                vad=vad_plugin,
                stt=openai.STT(),
                llm=llm_plugin,
                tts=tts_plugin,
                chat_ctx=openai.ChatContext().append(
                    role="system",
                    text=(
                        "You are SterileSpace, an AI voice operating copilot for cleanroom laboratory technicians "
                        "and surgeons who cannot physically touch screens or keyboards due to biohazard/sterile gloves. "
                        "Keep all verbal responses concise, professional, and clear. "
                        "Always call the appropriate lab tool when the operator commands an observation or fan speed change."
                    )
                ),
                fnc_ctx=tools
            )

            # Hook into interruption event for sub-180ms cutoff
            @agent.on("agent_speech_interrupted")
            def on_interrupted():
                logger.info("Agent speech interrupted by operator! Triggering state_manager cancellation.")
                asyncio.create_task(state_manager.request_interruption("vad_agent_speech_interrupted"))

            @agent.on("user_speech_committed")
            def on_user_speech(msg):
                if state_manager.has_active_tasks():
                    logger.info("New user speech turn committed while tool is in flight: cancelling pending tool.")
                    asyncio.create_task(state_manager.request_interruption("user_turn_override"))

            agent.start(ctx.room)
            await agent.say("SterileSpace copilot online. Hands-free voice active.", allow_interruptions=True)

        return entrypoint

    except ImportError as e:
        logger.warning("LiveKit plugins not fully configured or imported: %s", e)
        return None


def run_agent_worker():
    """Main worker startup."""
    entrypoint = setup_livekit_pipeline()
    if entrypoint:
        from livekit.agents import cli, WorkerOptions
        cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
    else:
        logger.info("SterileSpace agent worker initialized in standalone testing mode.")


if __name__ == "__main__":
    run_agent_worker()

