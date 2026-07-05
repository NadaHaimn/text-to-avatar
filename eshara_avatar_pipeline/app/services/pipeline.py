"""
pipeline.py
-----------
Async orchestrator for the avatar pipeline.

=== Critical fix: all blocking calls run in thread pool executor ===
`stt_service.transcribe_audio`, `youtube_service.download_audio`, and
`gemini_service.simplify_text` are all synchronous (CPU-bound or network I/O).
Calling them directly inside `async def` blocks the entire asyncio event loop —
no other request can be served while they run.

Solution: `asyncio.run_in_executor(None, fn, *args)` runs the blocking call
in Python's default ThreadPoolExecutor, freeing the event loop for other requests.
"""
import os
import time
import asyncio
import uuid
from functools import partial

from app.services import youtube_service, stt_service, gemini_service
from app.services.gloss_service import get_avatar_gloss_matcher
from app.services.avatar_url_service import build_avatar_player_url
from app.models.schemas import (
    InputType, GlossItem, PipelineTimings, TranslateResponse, ErrorCode
)
from app.config import get_settings


class PipelineError(Exception):
    """Raised with a structured error_code so the endpoint can return clean HTTP errors."""
    def __init__(self, message: str, error_code: ErrorCode):
        super().__init__(message)
        self.error_code = error_code


async def _run_sync(fn, *args):
    """Run a blocking sync function in the default thread-pool executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, fn, *args)


async def run_avatar_pipeline(
    input_type: InputType,
    content: str,
    simplify_with_gemini: bool = True,
    uploaded_audio_path: str | None = None,
    avatar: str = "marc",
    request_id: str | None = None,
) -> TranslateResponse:
    """
    Full pipeline: input → text → (Gemini) → gloss matching → avatar URL.
    All blocking I/O runs in a thread pool to keep the event loop free.
    """
    if request_id is None:
        request_id = str(uuid.uuid4())

    settings  = get_settings()
    warnings: list[str] = []
    timings: dict = {"total_seconds": 0.0}
    pipeline_start = time.time()

    audio_path   = None
    original_text = ""

    try:
        # ── Stage 1: Get text ──────────────────────────────────────────────────
        if input_type == InputType.youtube:
            try:
                audio_path, download_time = await _run_sync(
                    youtube_service.download_audio, content, settings.temp_audio_dir
                )
                timings["download_seconds"] = round(download_time, 3)
            except youtube_service.YouTubeDownloadError as e:
                raise PipelineError(str(e), ErrorCode.YOUTUBE_DOWNLOAD)

            try:
                original_text, transcribe_time = await _run_sync(
                    stt_service.transcribe_audio, audio_path
                )
                timings["transcription_seconds"] = round(transcribe_time, 3)
            except Exception as e:
                raise PipelineError(
                    f"Whisper transcription failed: {e}", ErrorCode.TRANSCRIPTION
                )

        elif input_type == InputType.audio:
            if not uploaded_audio_path:
                raise PipelineError(
                    "input_type=audio but no audio file provided", ErrorCode.INVALID_INPUT
                )
            audio_path = uploaded_audio_path
            try:
                original_text, transcribe_time = await _run_sync(
                    stt_service.transcribe_audio, audio_path
                )
                timings["transcription_seconds"] = round(transcribe_time, 3)
            except Exception as e:
                raise PipelineError(
                    f"Whisper transcription failed: {e}", ErrorCode.TRANSCRIPTION
                )

        elif input_type == InputType.text:
            original_text = content.strip()

        if not original_text:
            warnings.append("Empty text — check audio quality or input content")

        # ── Stage 2: Gemini simplification (optional) ──────────────────────────
        simplified_text   = None
        text_for_matching = original_text

        if simplify_with_gemini and original_text:
            try:
                simplified_text, gemini_time = await _run_sync(
                    gemini_service.simplify_text, original_text
                )
                timings["gemini_simplification_seconds"] = round(gemini_time, 3)
                text_for_matching = simplified_text
            except Exception as e:
                # Non-fatal: fall back to original text
                warnings.append(f"Gemini simplification failed, using original text: {e}")

        # ── Stage 3: Gloss matching ───────────────────────────────────────────
        matcher = get_avatar_gloss_matcher()
        match_start = time.time()
        # Gloss matching is pure Python CPU work — fast enough to not need executor
        raw_matches = matcher.match_text(text_for_matching or "")
        timings["gloss_matching_seconds"] = round(time.time() - match_start, 3)

        gloss_sequence   = [GlossItem(**m) for m in raw_matches]
        matched_glosses  = [g.gloss for g in gloss_sequence if g.matched]
        unmatched_words  = [g.word  for g in gloss_sequence if not g.matched]

        if unmatched_words:
            warnings.append(
                f"{len(unmatched_words)} word(s) skipped — no .sigml file for them"
            )
        if not matched_glosses:
            warnings.append(
                "No words matched — avatar_player_url will be empty. "
                "Try simplify_with_gemini=true or check available-glosses."
            )

        # ── Stage 4: Build avatar URL ─────────────────────────────────────────
        avatar_player_url = build_avatar_player_url(matched_glosses, avatar=avatar)
        timings["total_seconds"] = round(time.time() - pipeline_start, 3)

        return TranslateResponse(
            request_id      = request_id,
            original_text   = original_text,
            simplified_text = simplified_text,
            gloss_sequence  = gloss_sequence,
            matched_count   = len(matched_glosses),
            avatar_player_url = avatar_player_url,
            unmatched_words = unmatched_words,
            timings         = PipelineTimings(**timings),
            warnings        = warnings,
        )

    finally:
        # Always clean up YouTube temp file — uploaded audio is cleaned by the endpoint
        if input_type == InputType.youtube and audio_path and os.path.exists(audio_path):
            os.remove(audio_path)
