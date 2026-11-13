"""Vercel Python function: health endpoint (operation fixed in this file; see web/pyengine/solvant_api.py)."""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(_HERE, "..", "..", "pyengine"), os.path.join(os.getcwd(), "pyengine"), os.path.join(os.getcwd(), "web", "pyengine")):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

from solvant_api import EngineHandler  # noqa: E402


class handler(EngineHandler):  # noqa: N801 (Vercel looks for a top-level BaseHTTPRequestHandler subclass named "handler")
    OP = "health"
