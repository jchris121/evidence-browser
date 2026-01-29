#!/bin/bash
# Evidence Browser startup script
cd /home/hibbinz/clawd/evidence-browser
exec python3 -m uvicorn server:app --host 0.0.0.0 --port 8888
