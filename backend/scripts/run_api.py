"""
Run the real API for local development, reachable from phones on your network.

    python backend/scripts/run_api.py

Same as `make dev`, for Windows: uvicorn with auto-reload on 0.0.0.0:8000, started
from backend/ so .env and relative paths resolve. Binding 0.0.0.0 (not the uvicorn
default 127.0.0.1) is what lets the mobile app on a phone reach it.
"""

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def main() -> None:
    os.chdir(BACKEND)
    sys.path.insert(0, str(BACKEND))
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        reload_dirs=[str(BACKEND / "app")],
    )


if __name__ == "__main__":
    main()
