"""
main.py
-------
Eshara Avatar Pipeline — FastAPI entry point.

ONE SERVER, ONE PORT:
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

The avatar web-simulator is served as static files at /avatar
from the same FastAPI process — no separate HTTP server needed.

    API endpoints  -> http://localhost:8000/...
    Avatar player  -> http://localhost:8000/avatar/index.html?words=...
    Swagger docs   -> http://localhost:8000/docs

Android emulator  -> replace localhost with 10.0.2.2
Real device       -> replace localhost with your machine's LAN IP
"""
import os
import re
import uuid
import json
import shutil
import logging
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError

from app.models.schemas import (
    TranslateRequest, TranslateResponse, InputType,
    ErrorResponse, ErrorCode, StreamEvent, PipelineStage,
)
from app.services import stt_service
from app.services import pipeline as pipeline_svc
from app.services.pipeline import PipelineError
from app.services.gloss_service import get_avatar_gloss_matcher
from app.config import get_settings

logger = logging.getLogger(__name__)

_YOUTUBE_RE = re.compile(
    r"(https?://)?(www\.)?(youtube\.com/(watch\?v=|shorts/)|youtu\.be/)[\w\-]{11}"
)


# ── Startup / Shutdown ─────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # 1. Temp directory
    os.makedirs(settings.temp_audio_dir, exist_ok=True)

    # 2. Avatar static directory — validate it exists
    avatar_dir = Path(settings.avatar_static_dir).resolve()
    if not avatar_dir.exists():
        print(f"[WARN] Avatar static dir not found: {avatar_dir}")
        print("[WARN] Avatar will not be served. Check AVATAR_STATIC_DIR in .env")
    else:
        # 3. Always deploy our patched index.html into the web-simulator
        patch_src  = Path("avatar_patch/index.html").resolve()
        patch_dest = avatar_dir / "index.html"
        if patch_src.exists():
            shutil.copy2(patch_src, patch_dest)
            print(f"[INFO] Deployed patched index.html -> {patch_dest}")
        else:
            print(f"[WARN] avatar_patch/index.html not found at {patch_src}")

        # 4. Mount static files at /avatar
        app.mount("/avatar", StaticFiles(directory=str(avatar_dir), html=True), name="avatar")
        print(f"[INFO] Avatar simulator mounted at /avatar -> {avatar_dir}")

    # 5. Load Whisper model in thread pool (avoids blocking event loop on startup)
    print("[INFO] Loading Whisper model (first start may download weights)...")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, stt_service.get_whisper_model)
    print("[INFO] Whisper ready.")

    # 6. Pre-load gloss matcher
    print("[INFO] Loading available glosses...")
    try:
        matcher = get_avatar_gloss_matcher()
        print(f"[INFO] {len(matcher.normalized_to_original)} glosses available.")
    except FileNotFoundError:
        print("[WARN] data/available_glosses.json not found — run tools/extract_available_glosses.py")

    print(f"[INFO] Server ready. Avatar: {settings.avatar_player_base_url}")
    yield
    print("[INFO] Server shutting down.")


# ── OpenAPI metadata ──────────────────────────────────────────────────────────
_DESCRIPTION = """
## Eshara Avatar Pipeline API — v2.0

Converts **Arabic text / YouTube URL / audio file** into an `avatar_player_url`
that Flutter opens in a `WebViewWidget` — the 3D avatar animates automatically.

> **Single server setup:** The avatar web-simulator is served from the same
> FastAPI process at `/avatar`. No separate HTTP server needed.

### Quick Integration (Flutter)
```dart
final res = await http.post(Uri.parse('$base/translate'), ...);
final url = jsonDecode(res.body)['avatar_player_url'];
controller.loadRequest(Uri.parse(url)); // avatar plays immediately
```

### Endpoints
| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/health` | Status, version, gloss count |
| `POST` | `/translate` | Text / YouTube URL -> avatar URL |
| `POST` | `/translate-audio` | Audio file upload -> avatar URL |
| `GET`  | `/translate-stream` | SSE stream with stage progress |
| `GET`  | `/available-glosses` | All supported words |
| `GET`  | `/avatar/index.html` | The 3D avatar player itself |

### URL mapping (Android emulator)
```
Everything -> http://10.0.2.2:8000
API:          http://10.0.2.2:8000/translate
Avatar:       http://10.0.2.2:8000/avatar/index.html
```
"""

app = FastAPI(
    title        = "Eshara Avatar Pipeline API",
    description  = _DESCRIPTION,
    version      = "2.0.0",
    lifespan     = lifespan,
    contact      = {"name": "Eshara AI Team"},
    license_info = {"name": "MIT"},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins     = ["*"],
    allow_credentials = False,  # must be False with wildcard origin (CORS spec)
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)


# ── Validation error -> structured ErrorResponse ───────────────────────────────
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    detail = "; ".join(
        f"{'.'.join(str(l) for l in e['loc'])}: {e['msg']}"
        for e in exc.errors()
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=ErrorResponse(
            error_code=ErrorCode.INVALID_INPUT,
            detail=detail,
        ).model_dump(),
    )


# ── Internal helper ────────────────────────────────────────────────────────────
def _pipeline_error_to_http(e: PipelineError) -> HTTPException:
    status_map = {
        ErrorCode.INVALID_INPUT:    400,
        ErrorCode.YOUTUBE_DOWNLOAD: 422,
        ErrorCode.TRANSCRIPTION:    500,
        ErrorCode.GEMINI_ERROR:     500,
        ErrorCode.GLOSS_EMPTY:      200,
        ErrorCode.INTERNAL:         500,
    }
    return HTTPException(
        status_code=status_map.get(e.error_code, 500),
        detail=ErrorResponse(
            error_code=e.error_code,
            detail=str(e),
        ).model_dump(),
    )


# ── GET /health ───────────────────────────────────────────────────────────────
@app.get("/health", tags=["Infra"], summary="Server health check")
async def health_check():
    """
    Returns server status, version, avatar URL, and gloss count.
    Flutter should call this on app startup to confirm connectivity.
    """
    try:
        gloss_count = len(get_avatar_gloss_matcher().normalized_to_original)
    except Exception:
        gloss_count = 0
    settings = get_settings()
    return {
        "status":  "ok",
        "version": "2.0.0",
        "avatar_player_base_url":   settings.avatar_player_base_url,
        "available_glosses_count":  gloss_count,
    }


# ── POST /translate ───────────────────────────────────────────────────────────
@app.post(
    "/translate",
    response_model=TranslateResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid input"},
        422: {"model": ErrorResponse, "description": "YouTube download failed"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    tags=["Translation"],
    summary="Text or YouTube URL -> avatar player URL",
)
async def translate_content(request: TranslateRequest):
    """
    **Main endpoint.** Returns `avatar_player_url` — open it in `WebViewWidget`.

    - `input_type=text` — Arabic text (fastest, no download)
    - `input_type=youtube` — YouTube URL (downloads audio -> Whisper -> pipeline)
    - `simplify_with_gemini=true` — recommended for full sentences

    For audio file upload use `/translate-audio`.
    """
    if request.input_type == InputType.audio:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error_code=ErrorCode.INVALID_INPUT,
                detail="Use /translate-audio for audio file uploads",
            ).model_dump(),
        )

    if request.input_type == InputType.youtube:
        match = _YOUTUBE_RE.search(request.content)
        if not match:
            raise HTTPException(
                status_code=400,
                detail=ErrorResponse(
                    error_code=ErrorCode.INVALID_INPUT,
                    detail="content does not look like a valid YouTube URL (shorts and standard URLs supported)",
                ).model_dump(),
            )
        # Use only the matched valid URL part (drops accidental leading letters like 'أ' or trailing garbage)
        request.content = match.group(0)

    req_id = str(uuid.uuid4())
    try:
        result = await pipeline_svc.run_avatar_pipeline(
            input_type           = request.input_type,
            content              = request.content,
            simplify_with_gemini = request.simplify_with_gemini,
            avatar               = request.avatar,
            request_id           = req_id,
        )
        return result
    except PipelineError as e:
        raise _pipeline_error_to_http(e)
    except Exception as e:
        logger.exception("Unexpected error in /translate [%s]", req_id)
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                error_code=ErrorCode.INTERNAL,
                detail=str(e),
                request_id=req_id,
            ).model_dump(),
        )


# ── POST /translate-audio ─────────────────────────────────────────────────────
@app.post(
    "/translate-audio",
    response_model=TranslateResponse,
    responses={
        400: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
    tags=["Translation"],
    summary="Upload audio file -> avatar player URL",
)
async def translate_audio_file(
    file: UploadFile = File(..., description="Audio file: wav / mp3 / m4a / ogg"),
    simplify_with_gemini: bool = Form(
        default=True,
        description="Run Gemini simplification before gloss matching",
    ),
    avatar: str = Form(
        default="marc",
        description="The 3D avatar character to use",
    ),
):
    """
    Upload any audio file. Whisper transcribes it to Arabic, then runs the full pipeline.
    """
    settings  = get_settings()
    file_ext  = os.path.splitext(file.filename or "audio")[1].lower() or ".wav"
    req_id    = str(uuid.uuid4())
    temp_path = os.path.join(settings.temp_audio_dir, f"{req_id}{file_ext}")

    try:
        with open(temp_path, "wb") as buf:
            shutil.copyfileobj(file.file, buf)

        result = await pipeline_svc.run_avatar_pipeline(
            input_type           = InputType.audio,
            content              = "audio_upload",
            simplify_with_gemini = simplify_with_gemini,
            uploaded_audio_path  = temp_path,
            avatar               = avatar,
            request_id           = req_id,
        )
        return result
    except PipelineError as e:
        raise _pipeline_error_to_http(e)
    except Exception as e:
        logger.exception("Unexpected error in /translate-audio [%s]", req_id)
        raise HTTPException(
            status_code=500,
            detail=ErrorResponse(
                error_code=ErrorCode.INTERNAL,
                detail=str(e),
                request_id=req_id,
            ).model_dump(),
        )
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


# ── GET /translate-stream (SSE) ───────────────────────────────────────────────
@app.get(
    "/translate-stream",
    tags=["Translation"],
    summary="SSE: text -> avatar URL with stage-by-stage progress",
    response_class=StreamingResponse,
)
async def translate_stream(
    text: str,
    simplify_with_gemini: bool = True,
):
    """
    Server-Sent Events — ideal for long operations (Whisper / YouTube).
    Flutter receives real-time progress instead of a hanging HTTP request.

    **Events emitted (in order):**
    - `simplifying` (progress: 20) — if simplify_with_gemini=true
    - `matching`    (progress: 60)
    - `done`        (progress: 100) — includes full `TranslateResponse` in `data`
    - `error`       — if anything fails

    **Flutter SSE usage:**
    ```dart
    final uri = Uri.parse('$base/translate-stream')
      .replace(queryParameters: {'text': arabicText, 'simplify_with_gemini': 'true'});
    final client = http.Client();
    final req = http.Request('GET', uri);
    final res = await client.send(req);
    res.stream.transform(utf8.decoder).listen((chunk) {
      for (final line in chunk.split('\\n')) {
        if (line.startsWith('data: ')) {
          final event = jsonDecode(line.substring(6));
          // event['stage'], event['progress'], event['data']
        }
      }
    });
    ```
    """
    if not text.strip():
        raise HTTPException(status_code=400, detail="text query param must not be empty")

    async def event_generator() -> AsyncGenerator[str, None]:
        def _sse(event: StreamEvent) -> str:
            return f"data: {event.model_dump_json()}\n\n"

        req_id = str(uuid.uuid4())
        try:
            if simplify_with_gemini:
                yield _sse(StreamEvent(
                    stage    = PipelineStage.simplifying,
                    message  = "Simplifying text with Gemini...",
                    progress = 20,
                ))
                await asyncio.sleep(0)  # yield control to event loop

            yield _sse(StreamEvent(
                stage    = PipelineStage.matching,
                message  = "Matching words to sign glosses...",
                progress = 60,
            ))
            await asyncio.sleep(0)

            result = await pipeline_svc.run_avatar_pipeline(
                input_type           = InputType.text,
                content              = text,
                simplify_with_gemini = simplify_with_gemini,
                request_id           = req_id,
            )

            yield _sse(StreamEvent(
                stage    = PipelineStage.done,
                message  = f"Done — {result.matched_count} word(s) matched.",
                progress = 100,
                data     = result,
            ))

        except PipelineError as e:
            yield _sse(StreamEvent(
                stage   = PipelineStage.error,
                message = str(e),
                progress= 0,
                error   = e.error_code.value,
            ))
        except Exception as e:
            logger.exception("SSE pipeline error [%s]", req_id)
            yield _sse(StreamEvent(
                stage   = PipelineStage.error,
                message = str(e),
                progress= 0,
                error   = ErrorCode.INTERNAL.value,
            ))

    return StreamingResponse(
        event_generator(),
        media_type = "text/event-stream",
        headers    = {
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering":"no",   # disables nginx buffering for SSE
        },
    )


# ── GET /available-glosses ────────────────────────────────────────────────────
@app.get(
    "/available-glosses",
    tags=["Infra"],
    summary="All words the avatar can sign",
)
async def list_available_glosses():
    """
    Every word that has a matching `.sigml` file — guaranteed to animate.
    Use for autocomplete or vocabulary display in Flutter.
    """
    matcher = get_avatar_gloss_matcher()
    return {
        "count":   len(matcher.normalized_to_original),
        "glosses": sorted(matcher.normalized_to_original.values()),
    }

