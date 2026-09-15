"""Dual-friendly launcher for the OSWorld guest server under E2B.

Upstream desktop_env/server/main.py runs `app.run(debug=True, host="0.0.0.0")`
only under its own `__main__` guard. We import the same Flask `app` and run it
without the reloader (debug=False), so the process tree stays simple and can be
snapshotted cleanly by the E2B template build.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from main import app  # noqa: E402

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
