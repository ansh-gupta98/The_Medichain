"""
Railway / Production entry point.
Reads PORT directly from os.environ — no shell, no $PORT expansion issue.
"""
import os
import uvicorn

port = int(os.environ.get("PORT", 8000))
print(f"[MediChain] Starting on port {port}", flush=True)

uvicorn.run(
    "main:app",
    host="0.0.0.0",
    port=port,
    workers=1,        # multi-worker needs __main__ guard — use 1 worker in container
    log_level="info",
)
