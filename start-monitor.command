#!/bin/bash

# Monitor Cen Launcher
# This script starts the price monitoring application

PROJECT_DIR="/Users/a12345678/Pliki/Claude/Monitor cen"
cd "$PROJECT_DIR" || exit 1

# Activate virtual environment
source .venv/bin/activate

# Open browser (give server a moment to start)
sleep 2
open "http://localhost:5000" &

# Run Flask app
python app.py
