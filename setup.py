#!/usr/bin/env python3
"""
IntentLead AI — Setup & Configuration Launcher
Convenience shortcut to scripts/setup.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

if __name__ == "__main__":
    script = Path(__file__).resolve().parent / "scripts" / "setup.py"
    if not script.exists():
        print(f"Error: Setup script not found at {script}", file=sys.stderr)
        sys.exit(1)
    
    cmd = [sys.executable, str(script)] + sys.argv[1:]
    sys.exit(subprocess.call(cmd))
