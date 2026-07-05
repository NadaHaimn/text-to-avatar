"""
schemas.py
----------
Pydantic models for request/response. Designed for clean Flutter consumption:
- Every response includes request_id for debugging
- matched_count is pre-computed so Flutter doesn't parse the array
- ErrorResponse has an error_code for machine-readable handling in Dart
- SSE event model for streaming endpoint
"""
import uuid as _uuid
from pydantic import BaseModel, Field, field_validator, AnyHttpUrl
from typing import Optional, Literal
from enum import Enum


class InputType(str, Enum):
    youtube = "youtube"
    audio   = "audio"
    text    = "text"


class TranslateRequest(BaseModel):
    input_type: InputType = Field(
        ...,
        examples=["text"],
        description="'text' for Arabic text, 'youtube' for a YouTube URL",
    )
    content: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Arabic text OR a YouTube URL, depending on input_type",
        examples=["أنا أذهب إلى المدرسة"],
    )
    simplify_with_gemini: bool = Field(
        default=True,
        description="Run Gemini simplification before gloss matching (recommended for full sentences)",
    )
    avatar: str = Field(
        default="marc",
        description="The 3D avatar character to use (e.g., 'marc', 'anna', 'francoise', 'luna')",
    )

    @field_validator("content")
    @classmethod
    def content_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("content must not be blank")
        return v


class GlossItem(BaseModel):
    word: str  = Field(..., description="Original word from the input text")
    gloss: str = Field(..., description="Matched gloss name (= .sigml filename, guaranteed to exist)")
    match_score: float = Field(..., ge=0, le=100, description="Fuzzy match confidence 0-100")
    matched: bool = Field(..., description="True = avatar will animate this word")


class PipelineTimings(BaseModel):
    download_seconds:              Optional[float] = None
    transcription_seconds:         Optional[float] = None
    gemini_simplification_seconds: Optional[float] = None
    gloss_matching_seconds:        Optional[float] = None
    total_seconds: float = 0.0


class TranslateResponse(BaseModel):
    request_id: str = Field(
        default_factory=lambda: str(_uuid.uuid4()),
        description="Unique ID for this request — use for debugging/logging",
    )
    original_text:   str
    simplified_text: Optional[str] = None
    gloss_sequence:  list[GlossItem]
    matched_count:   int = Field(
        ...,
        description="Number of words the avatar will actually animate (pre-computed for Flutter)",
    )
    avatar_player_url: str = Field(
        ...,
        description="Open directly in WebViewWidget — avatar auto-plays on load",
    )
    unmatched_words: list[str] = Field(
        default_factory=list,
        description="Words with no .sigml file — skipped silently by the avatar",
    )
    timings:  PipelineTimings
    warnings: list[str] = Field(default_factory=list)


# ── SSE event shape (for /translate-stream) ───────────────────────────────────
class PipelineStage(str, Enum):
    downloading   = "downloading"
    transcribing  = "transcribing"
    simplifying   = "simplifying"
    matching      = "matching"
    done          = "done"
    error         = "error"


class StreamEvent(BaseModel):
    stage:   PipelineStage
    message: str
    progress: int = Field(default=0, ge=0, le=100, description="0-100 completion estimate")
    data: Optional[TranslateResponse] = None  # only on stage=done
    error: Optional[str] = None               # only on stage=error


# ── Error response ─────────────────────────────────────────────────────────────
class ErrorCode(str, Enum):
    INVALID_INPUT      = "INVALID_INPUT"
    YOUTUBE_DOWNLOAD   = "YOUTUBE_DOWNLOAD"
    TRANSCRIPTION      = "TRANSCRIPTION"
    GEMINI_ERROR       = "GEMINI_ERROR"
    GLOSS_EMPTY        = "GLOSS_EMPTY"
    INTERNAL           = "INTERNAL_ERROR"


class ErrorResponse(BaseModel):
    error_code: ErrorCode = Field(..., description="Machine-readable code for Flutter switch/case")
    detail: str           = Field(..., description="Human-readable error message")
    request_id: str       = Field(default_factory=lambda: str(_uuid.uuid4()))
