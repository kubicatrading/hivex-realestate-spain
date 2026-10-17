import os
import sys
import traceback

# Guarantee repository root is in Python module search path for Vercel
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from app.api.main import app
except Exception as _import_err:
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    _tb = traceback.format_exc()
    app = FastAPI(title="HIVEX Boot Diagnostic")

    @app.api_route("/{path_name:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
    def _boot_error(path_name: str = ""):
        return JSONResponse(
            status_code=500,
            content={"status": "boot_error", "error": str(_import_err), "traceback": _tb},
        )


