"""
Railway / Production entry point.
Reads PORT directly from os.environ — no shell, no $PORT expansion issue.
"""
import os
import uvicorn

port = int(os.environ.get("PORT", 8000))
print(f"[MediChain] Starting on port {port}", flush=True)

uvicorn.run(
    "main:app",      # main.py at project root
    host="0.0.0.0",
    port=port,
    workers=2,
    log_level="info",
)
