import sys
import os

print("=== MediChain Starting ===", flush=True)
print(f"Python: {sys.version}", flush=True)
print(f"Working dir: {os.getcwd()}", flush=True)
print(f"Files here: {os.listdir('.')}", flush=True)

backend_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")
print(f"Backend path: {backend_path}", flush=True)
print(f"Backend exists: {os.path.exists(backend_path)}", flush=True)
sys.path.insert(0, backend_path)

print("Importing FastAPI app...", flush=True)
try:
    from main import app
    print("App imported successfully!", flush=True)
except Exception as e:
    print(f"IMPORT ERROR: {e}", flush=True)
    import traceback
    traceback.print_exc()
    raise
