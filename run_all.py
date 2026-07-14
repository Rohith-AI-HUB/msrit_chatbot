"""Start all 4 microservices as subprocesses and wait."""
import subprocess, sys, time, os, signal

BASE = r"C:\Users\rohit\Documents\msrit_chatbot"
SERVICES = BASE + r"\services"
PYTHONPATH = SERVICES

PROCS = []

services = [
    ("retrieval", 8001, SERVICES + r"\retrieval-service"),
    ("session",   8003, SERVICES + r"\session-service"),
    ("llm",       8002, SERVICES + r"\llm-service"),
]

for name, port, cwd in services:
    env = os.environ.copy()
    env["PYTHONPATH"] = PYTHONPATH
    p = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app",
         "--host", "0.0.0.0", "--port", str(port), "--log-level", "warning"],
        cwd=cwd, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    PROCS.append(p)
    print(f"Started {name} (pid={p.pid}) on :{port}")

print("Waiting 45s for retrieval to load embeddings model...")
time.sleep(45)

# Start orchestrator last
name, port, cwd = "orchestrator", 8000, SERVICES + r"\chat-orchestrator"
env = os.environ.copy()
env["PYTHONPATH"] = PYTHONPATH
p = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "main:app",
     "--host", "0.0.0.0", "--port", str(port), "--log-level", "warning"],
    cwd=cwd, env=env,
    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
)
PROCS.append(p)
print(f"Started orchestrator (pid={p.pid}) on :{port}")

time.sleep(5)

import urllib.request, json
for name, port in [("retrieval", 8001), ("llm", 8002), ("session", 8003), ("orchestrator", 8000)]:
    try:
        r = urllib.request.urlopen(f"http://localhost:{port}/health", timeout=5)
        print(f"  {name}: HEALTHY")
    except Exception as e:
        print(f"  {name}: FAILED - {e}")

print("\nServices running. Press Ctrl+C to stop all.")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\nShutting down...")
    for p in PROCS:
        p.terminate()
    for p in PROCS:
        p.wait(timeout=5)
    print("All stopped.")
