"""
Run the dashboard web app.

Usage:
    python scripts/run_dashboard.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uvicorn

if __name__ == "__main__":
    uvicorn.run("src.dashboard.app:app", host="0.0.0.0", port=8000, reload=False)
