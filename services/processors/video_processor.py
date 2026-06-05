"""Video content extraction using moviepy, whisper, opencv, and transformers BLIP."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from services.processors.base import ExtractedDocument

logger = logging.getLogger(__name__)


class VideoProcessor:
    """Extracts text transcripts and visual captions from video files."""

    supported_extensions = {".mp4", ".mov", ".avi", ".mkv"}

    def process(self, file_path: Path | str) -> ExtractedDocument:
        """Extract transcription and frame captions from video."""
        path = Path(file_path)
        temp_audio_path = None
        try:
            # Lazy imports to optimize startup speed
            import cv2
            import whisper
            from PIL import Image
            from transformers import BlipForConditionalGeneration, BlipProcessor
            
            # Since moviepy can be finicky or missing, we handle moviepy/ffmpeg loading
            try:
                from moviepy.editor import VideoFileClip
            except ImportError as exc:
                raise RuntimeError("moviepy is required for video audio extraction") from exc

            logger.info("Processing video file: %s", path)
            
            # 1. Extract metadata & Keyframes
            cap = cv2.VideoCapture(str(path))
            if not cap.isOpened():
                raise ValueError("Could not open video file via OpenCV")

            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            duration = frame_count / fps if fps else 0.0

            metadata = {
                "duration_seconds": duration,
                "resolution": f"{width}x{height}",
                "fps": fps,
                "frame_count": frame_count,
            }

            # Select 3-5 keyframes evenly spaced
            num_keyframes = min(5, max(3, frame_count // (int(fps) * 5) or 3))
            num_keyframes = min(num_keyframes, frame_count)
            frame_indices = []
            if frame_count > 0 and num_keyframes > 0:
                frame_indices = [int(i * frame_count / num_keyframes) for i in range(num_keyframes)]

            captions = []
            if frame_indices:
                logger.info("Extracting %d keyframes from video", len(frame_indices))
                # Load BLIP image captioner
                blip_processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
                blip_model = BlipForConditionalGeneration.from_pretrained("Salesforce/blip-image-captioning-base")

                for idx in frame_indices:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                    ret, frame = cap.read()
                    if ret and frame is not None:
                        # Convert BGR to RGB PIL Image
                        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        pil_img = Image.fromarray(rgb_frame)
                        
                        inputs = blip_processor(pil_img, return_tensors="pt")
                        out = blip_model.generate(**inputs, max_new_tokens=50)
                        caption = blip_processor.decode(out[0], skip_special_tokens=True)
                        captions.append(f"Frame at {idx/fps:.1f}s: {caption}")
            
            cap.release()

            # 2. Extract and transcribe audio
            transcription = ""
            try:
                clip = VideoFileClip(str(path))
                if clip.audio is not None:
                    # Write to a temp wav file
                    fd, temp_audio_path = tempfile.mkstemp(suffix=".wav")
                    os.close(fd)
                    
                    logger.info("Extracting audio to %s", temp_audio_path)
                    clip.audio.write_audiofile(temp_audio_path, verbose=False, logger=None)
                    clip.close()

                    # Transcribe using Whisper
                    logger.info("Transcribing audio using Whisper (tiny)")
                    whisper_model = whisper.load_model("tiny")
                    result = whisper_model.transcribe(temp_audio_path)
                    transcription = result.get("text", "").strip()
                else:
                    logger.info("No audio stream found in video clip")
                    clip.close()
            except Exception as audio_exc:
                logger.warning("Could not extract/transcribe audio from video %s: %s", path, audio_exc)

            # Combine transcription and captions
            full_content_parts = []
            if transcription:
                full_content_parts.append(f"Audio Transcription:\n{transcription}")
            if captions:
                full_content_parts.append("Visual Keyframe Captions:\n" + "\n".join(captions))
            
            content = "\n\n".join(full_content_parts)

            return {
                "file_name": path.name,
                "content": content,
                "metadata": metadata,
                "file_type": "video",
            }

        except Exception as exc:
            logger.exception("Failed to process video %s", path)
            raise ValueError(f"Could not process video file: {path}") from exc
        finally:
            if temp_audio_path and os.path.exists(temp_audio_path):
                try:
                    os.remove(temp_audio_path)
                except OSError:
                    pass
