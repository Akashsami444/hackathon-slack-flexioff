import os
from fastapi import FastAPI
from .slack_events import router as slack_router
from .config import settings  # Will error immediately at app startup if anything is missing

app = FastAPI()
app.include_router(slack_router)