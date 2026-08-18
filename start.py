import os
import uvicorn

port = int(os.environ.get("PORT", 8000))
print(f"Starting on port {port}", flush=True)
uvicorn.run("run:app", host="0.0.0.0", port=port, workers=1)
