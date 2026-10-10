"""
Railway / Render / Production entry point.
Reads PORT directly from os.environ.
Limits concurrency and threads to strictly prevent 512MB OOM crashes.
"""
import os

# Limit thread pools to 1 to prevent memory blowup on multi-core cloud containers
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    print(f"[MediChain] Starting on port {port} with workers=1 (low-memory mode)", flush=True)

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        workers=1,
        log_level="info",
    )
