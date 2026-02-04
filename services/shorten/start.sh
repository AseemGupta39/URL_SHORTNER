#!/bin/bash
# Start Redis sidecar on loopback (for pool vs network isolation test)
redis-server --daemonize yes --appendonly no --bind 127.0.0.1 --port 6379

# Start the app
exec uvicorn main:app --host 0.0.0.0 --port 8001
