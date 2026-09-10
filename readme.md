# SterileSpace (The Dirty-Hands / Sterile-Lab Voice Operating Copilot)

> Built for the **Rime Voice AI Hackathon**.

The complete project is located in [`sterilespace/`](sterilespace/):

- **Benchmark & Evidence Report**: [`sterilespace/RIME_EVIDENCE.md`](sterilespace/RIME_EVIDENCE.md)
- **Project Documentation**: [`sterilespace/README.md`](sterilespace/README.md)
- **Automated CLI Benchmark**: `python sterilespace/evals/test_interruption.py`
- **FastAPI Web HUD Server**: `python -m uvicorn server.app:app --app-dir sterilespace --host 0.0.0.0 --port 8000 --reload`
- **LiveKit Agent Worker**: `python sterilespace/agent/main.py`

