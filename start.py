"""
Railway / Production entry point.
Reads PORT directly from os.environ — no shell, no $PORT expansion issue.
"""
import os

# Limit thread pools to 1 to prevent memory blowup on multi-core cloud containers
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

import uvicorn

port = int(os.environ.get("PORT", 8000))
print(f"[MediChain] Starting on port {port}", flush=True)

uvicorn.run(
    "main:app",
    host="0.0.0.0",
    port=port,
    workers=1,
    log_level="info",
)
