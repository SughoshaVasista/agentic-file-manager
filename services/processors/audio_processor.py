"""Audio content extraction using pydub and Whisper."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from services.processors.base import ExtractedDocument

logger = logging.getLogger(__name__)


class AudioProcessor:
    """Extracts metadata and transcripts from audio files."""

    supported_extensions = {".mp3", ".wav", ".m4a", ".flac"}

    def process(self, file_path: Path | str) -> ExtractedDocument:
        """Extract transcript and metadata from audio."""
        path = Path(file_path)
        try:
            # Lazy imports
            import whisper
            from pydub import AudioSegment

            logger.info("Processing audio file: %s", path)
            audio = AudioSegment.from_file(path)

            duration_seconds = len(audio) / 1000.0
            metadata = {
                "duration_seconds": duration_seconds,
                "sample_rate": audio.frame_rate,
                "channels": audio.channels,
            }

            # Split into chunks of 30 seconds to handle long files robustly
            chunk_length_ms = 30000
            chunks = []
            for i in range(0, len(audio), chunk_length_ms):
                chunks.append(audio[i : i + chunk_length_ms])

            logger.info("Transcribing audio split into %d chunks using Whisper (tiny)", len(chunks))
            whisper_model = whisper.load_model("tiny")
            transcripts = []

            for index, chunk in enumerate(chunks):
                fd, temp_chunk_path = tempfile.mkstemp(suffix=".wav")
                os.close(fd)
                try:
                    chunk.export(temp_chunk_path, format="wav")
                    result = whisper_model.transcribe(temp_chunk_path)
                    text = result.get("text", "").strip()
                    if text:
                        transcripts.append(text)
                finally:
                    if os.path.exists(temp_chunk_path):
                        os.remove(temp_chunk_path)

            content = " ".join(transcripts)

            return {
                "file_name": path.name,
                "content": content,
                "metadata": metadata,
                "file_type": "audio",
            }

        except Exception as exc:
            logger.exception("Failed to process audio %s", path)
            raise ValueError(f"Could not process audio file: {path}") from exc
