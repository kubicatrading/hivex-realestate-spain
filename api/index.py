import os
import sys

# Guarantee repository root is in Python module search path for Vercel
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.main import app

# Export app and handler for Vercel ASGI runner (Trigger fresh deployment)
handler = app
