"""Entry point used by the host: uvicorn app.server:app"""
from .main import create_app

app = create_app()
