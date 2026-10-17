import os
import sys
import traceback
from fastapi import FastAPI
from fastapi.responses import JSONResponse

# Guarantee repository root is in Python module search path for Vercel
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

app = FastAPI(title="HIVEX Real Estate Intelligence")

try:
    from app.api.main import app as _real_app
    app = _real_app
except Exception as _import_err:
    _tb = traceback.format_exc()

    @app.api_route("/{path_name:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
    def _boot_error(path_name: str = ""):
        return JSONResponse(
            status_code=200,
            content={"status": "boot_error", "error": str(_import_err), "traceback": _tb},
        )
