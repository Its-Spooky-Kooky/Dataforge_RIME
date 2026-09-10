"""
Automated Barge-In Benchmark & Phonetic Delivery Evaluation Suite.
Tests sub-180ms cancellation fencing, lab nomenclature normalization,
and atomic state integrity under operator interruptions.
"""

import sys
import os
import json
import time
import asyncio
from pathlib import Path

# Ensure sterilespace root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from agent.normalizer import LabPhoneticNormalizer, normalize_for_rime
from agent.state_manager import AgentStateManager
from server.mock_iot import MockLabStore


def run_phonetic_normalization_tests(fixtures_path: Path) -> dict:
    """Test 1: Evaluates phonetic preprocessor on scientific laboratory tokens."""
    print("\n" + "=" * 70)
    print("TEST 1: PHONETIC & SCIENTIFIC NORMALIZATION ACCURACY")
    print("=" * 70)

    with open(fixtures_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    fixtures = data.get("phonetic_normalization_fixtures", [])
    passed = 0
    total = len(fixtures)
    results = []

    normalizer = LabPhoneticNormalizer()

    for idx, fix in enumerate(fixtures, 1):
        raw_text = fix["input"]
        expected_items = fix["expected_contains"]
        normalized = normalizer.normalize(raw_text)

        all_present = True
        missing = []
        for exp in expected_items:
            if exp.lower() not in normalized.lower():
                all_present = False
                missing.append(exp)

        if all_present:
            passed += 1
            status = "PASS [OK]"
        else:
            status = f"FAIL (Missing: {missing})"

        print(f"[{idx}/{total}] {status}")
        print(f"   Raw:        \"{raw_text}\"")
        print(f"   Normalized: \"{normalized}\"")

        results.append({
            "fixture": idx,
            "status": "PASS" if all_present else "FAIL",
            "raw": raw_text,
            "normalized": normalized,
            "missing": missing
        })

    accuracy = (passed / total) * 100.0 if total > 0 else 0
    print(f"\nPhonetic Normalization Result: {passed}/{total} Passed ({accuracy:.1f}%)")
    return {"passed": passed, "total": total, "accuracy_pct": accuracy, "results": results}


async def run_barge_in_latency_benchmarks(num_trials: int = 5) -> dict:
    """
    Test 2: Evaluates hard voice engineering requirement:
    Interruption & recovery with sub-180ms audio and async tool task cutoff.
    """
    print("\n" + "=" * 70)
    print("TEST 2: BARGE-IN INTERRUPTION & AUDIO CUTOFF BENCHMARK (<180ms Target)")
    print("=" * 70)

    latencies = []
    trial_records = []

    for trial in range(1, num_trials + 1):
        test_store = MockLabStore()
        test_mgr = AgentStateManager()

        audio_drain_called = False

        def mock_audio_drain():
            nonlocal audio_drain_called
            audio_drain_called = True

        test_mgr.register_audio_stop_callback(mock_audio_drain)

        # Launch simulated 2.5s asynchronous tool inside cancellation fence
        cancelled_flag = False

        async def worker_coro():
            nonlocal cancelled_flag
            try:
                await test_mgr.execute_fenced_tool(
                    "log_sample_observation",
                    test_store.log_sample_observation,
                    tube_id="4B",
                    metric="oxidation",
                    value=15.0,
                    unit="%",
                    delay_seconds=2.5
                )
            except asyncio.CancelledError:
                cancelled_flag = True

        tool_task = asyncio.create_task(worker_coro())

        # Let the tool run in-flight for 250ms
        await asyncio.sleep(0.25)

        # Operator interrupts (Voice Activity Detected)
        t_start = time.perf_counter()
        cutoff_result = await test_mgr.request_interruption("operator_barge_in_benchmark")
        t_end = time.perf_counter()

        # Await task cancellation finalization
        try:
            await tool_task
        except asyncio.CancelledError:
            cancelled_flag = True

        measured_latency_ms = (t_end - t_start) * 1000.0
        latencies.append(measured_latency_ms)

        target_met = measured_latency_ms < 180.0
        status = "PASSED (< 180ms)" if target_met else "FAILED"

        print(f"Trial {trial}/{num_trials}: Cutoff Latency = {measured_latency_ms:6.2f} ms | "
              f"Audio Drained: {audio_drain_called} | Task Cancelled: {cancelled_flag} -> {status}")

        trial_records.append({
            "trial": trial,
            "cutoff_latency_ms": round(measured_latency_ms, 2),
            "audio_drained": audio_drain_called,
            "task_cancelled": cancelled_flag,
            "target_met": target_met
        })

    avg_lat = sum(latencies) / len(latencies)
    min_lat = min(latencies)
    max_lat = max(latencies)

    print(f"\nBenchmark Summary ({num_trials} trials):")
    print(f"   Min Cutoff Latency:  {min_lat:.2f} ms")
    print(f"   Max Cutoff Latency:  {max_lat:.2f} ms")
    print(f"   Avg Cutoff Latency:  {avg_lat:.2f} ms")
    print(f"   Rubric Requirement: < 180.00 ms")
    print(f"   Status:             {'ALL TRIALS PASSED' if max_lat < 180.0 else 'FAILED'}")

    return {
        "trials": trial_records,
        "min_latency_ms": round(min_lat, 2),
        "max_latency_ms": round(max_lat, 2),
        "avg_latency_ms": round(avg_lat, 2),
        "all_passed": max_lat < 180.0
    }


async def run_state_integrity_test() -> dict:
    """Test 3: Verifies atomic rollback - cancelled tool does NOT pollute lab store."""
    print("\n" + "=" * 70)
    print("TEST 3: ATOMIC DATABASE INTEGRITY UNDER INTERRUPTION")
    print("=" * 70)

    test_store = MockLabStore()
    test_mgr = AgentStateManager()

    original_val = test_store.samples["4B"]["value"]
    print(f"Pre-test: Tube 4B oxidation = {original_val}%")

    async def in_flight_write():
        await test_mgr.execute_fenced_tool(
            "log_sample_observation",
            test_store.log_sample_observation,
            tube_id="4B",
            metric="oxidation",
            value=99.9,  # Unintended value that should be aborted
            unit="%",
            delay_seconds=2.0
        )

    write_task = asyncio.create_task(in_flight_write())
    await asyncio.sleep(0.3)

    # Abort
    await test_mgr.request_interruption("emergency_voice_abort")
    try:
        await write_task
    except asyncio.CancelledError:
        pass

    post_val = test_store.samples["4B"]["value"]
    print(f"Post-test: Tube 4B oxidation = {post_val}%")

    passed = (post_val == original_val)
    print(f"Atomic Rollback Verification: {'PASS (No Corrupted Commit)' if passed else 'FAIL (Dirty Write Occurred)'}")

    return {"passed": passed, "pre_value": original_val, "post_value": post_val}


async def main():
    fixtures_path = BASE_DIR / "evals" / "fixtures.json"

    print("======================================================================")
    print("   STERILESPACE - AUTOMATED BENCHMARK & EVIDENCE EVALUATION SUITE     ")
    print("======================================================================")

    # 1. Phonetic Normalization Test
    norm_report = run_phonetic_normalization_tests(fixtures_path)

    # 2. Barge-In Latency Benchmark
    latency_report = await run_barge_in_latency_benchmarks(num_trials=5)

    # 3. State Integrity Test
    integrity_report = await run_state_integrity_test()

    print("\n" + "=" * 70)
    print("FINAL EVALUATION VERDICT")
    print("=" * 70)
    all_ok = (
        norm_report["accuracy_pct"] == 100.0 and
        latency_report["all_passed"] and
        integrity_report["passed"]
    )
    if all_ok:
        print(">> ALL BENCHMARKS PASSED! Hard voice engineering requirements verified. <<")
    else:
        print(">> SOME BENCHMARKS FAILED. Review output above. <<")

    return all_ok


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
