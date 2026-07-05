"""
config.py
---------
All settings are read from .env — no code changes needed for different environments.
"""
import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    # --- Gemini ---
    gemini_api_key: str
    gemini_model: str = "gemini-2.5-flash"

    # --- Whisper ---
    whisper_model_size:    str = "small"
    whisper_device:        str = "cpu"
    whisper_compute_type:  str = "int8"

    # --- Gloss vocabulary ---
    available_glosses_path: str = "data/available_glosses.json"

    # --- Fuzzy match threshold (0-100) ---
    # High on purpose: a wrong match = wrong sign shown to user
    fuzzy_match_threshold: int = 90

    # --- Avatar static files ---
    # Path to the algerianSignLanguage-avatar/web-simulator directory.
    # FastAPI serves it at /avatar — no separate HTTP server needed.
    avatar_static_dir: str = "../algerianSignLanguage-avatar/web-simulator"

    # --- Avatar player URL (built from avatar_static_dir mount) ---
    # Default points to the /avatar route on this same FastAPI server.
    # Change to https://... when deploying.
    avatar_player_base_url: str = "http://localhost:8000/avatar/index.html"

    # --- Temp directory for audio processing ---
    temp_audio_dir: str = "temp_audio"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
