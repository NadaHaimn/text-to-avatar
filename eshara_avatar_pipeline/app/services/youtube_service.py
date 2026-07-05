"""
youtube_service.py
-------------------
Downloads audio from a YouTube URL and returns a local WAV file path.

=== Format Selection Strategy ===
"bestaudio/best" alone fails for some YouTube videos (age-restricted,
music videos, region-locked). We use a cascading fallback chain:
  1. Audio-only streams (no video download at all) — fastest
  2. Any audio-only stream as fallback
  3. Worst-quality video as last resort (then ffmpeg extracts audio)
This guarantees we can download virtually any public YouTube video.

=== Optimizations ===
1. Audio-only download (bestaudio) skips video track entirely.
2. FFmpegExtractAudio converts directly to WAV 16kHz mono —
   exactly what Whisper needs, saves a re-encode step.
3. concurrent_fragment_downloads=4 speeds up DASH streams.
"""
import re
import yt_dlp
import time
import os
import uuid
import glob
from pathlib import Path
import imageio_ffmpeg


class YouTubeDownloadError(Exception):
    pass


def _strip_ansi(text: str) -> str:
    """Remove ANSI color escape codes from yt-dlp error strings."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def download_audio(youtube_url: str, output_dir: str) -> tuple[str, float]:
    """
    Downloads audio-only from a YouTube video and converts to WAV 16kHz mono
    (the ideal format for Whisper — avoids any re-encoding step).

    Returns:
        (path to .wav file, elapsed seconds)
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Unique filename per request — avoids collisions on concurrent requests
    file_id = str(uuid.uuid4())
    output_template = os.path.join(output_dir, f"{file_id}.%(ext)s")

    ydl_opts = {
        # Cascading format fallback — handles age-restricted, music, region-locked videos:
        #   1st choice: best audio-only webm (opus codec, native on YouTube)
        #   2nd choice: best audio-only m4a (AAC, very common)
        #   3rd choice: any audio-only stream
        #   4th choice: worst full video (ffmpeg will strip audio from it)
        "format": (
            "bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio[ext=opus]"
            "/bestaudio/worstaudio/worst"
        ),
        "ffmpeg_location": imageio_ffmpeg.get_ffmpeg_exe(),
        "outtmpl": output_template,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "wav",
        }],
        # 16kHz mono = exactly what Whisper needs, pre-converted to save time
        "postprocessor_args": {
            "ffmpeg": ["-ar", "16000", "-ac", "1"]
        },
        "quiet": True,
        "no_warnings": True,
        "concurrent_fragment_downloads": 4,
        "noplaylist": True,      # single video even if URL is inside a playlist
        "extractor_retries": 3,  # retry on transient YouTube errors
        "fragment_retries": 3,
    }

    start = time.time()
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([youtube_url])
    except yt_dlp.utils.DownloadError as e:
        # Strip ANSI color codes so the error is readable in the API response
        clean_msg = _strip_ansi(str(e))
        raise YouTubeDownloadError(f"فشل تنزيل الفيديو: {clean_msg}")

    elapsed = time.time() - start

    expected_path = os.path.join(output_dir, f"{file_id}.wav")
    if not os.path.exists(expected_path):
        # If source file exists but .wav doesn't — ffmpeg likely missing
        source_files = glob.glob(os.path.join(output_dir, f"{file_id}.*"))
        if source_files:
            raise YouTubeDownloadError(
                f"Download succeeded but ffmpeg failed to convert the audio. "
                f"Is ffmpeg installed? Try: ffmpeg -version\n"
                f"Source files: {source_files}"
            )
        raise YouTubeDownloadError(
            "Download succeeded but WAV file not found after processing — "
            "ensure ffmpeg is installed and in PATH."
        )

    return expected_path, elapsed
