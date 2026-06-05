"""GIF content extraction using Pillow, pytesseract (OCR), and BLIP."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PIL import Image
from services.processors.base import ExtractedDocument
from services.processors.image_processor import ImageProcessor

logger = logging.getLogger(__name__)


class GIFProcessor:
    """Extracts OCR text and caption descriptions from a GIF file."""

    supported_extensions = {".gif"}

    def process(self, file_path: Path | str) -> ExtractedDocument:
        """Extract content from GIF."""
        path = Path(file_path)
        try:
            logger.info("Processing GIF file: %s", path)
            gif = Image.open(path)

            # Determine frame count
            frame_count = 0
            try:
                while True:
                    frame_count += 1
                    gif.seek(frame_count)
            except EOFError:
                pass
            
            # Reset to first frame
            gif.seek(0)
            
            # Extract duration metadata if present
            duration_ms = 0
            try:
                duration_ms = gif.info.get("duration", 0) * frame_count
            except Exception:
                pass
            
            metadata = {
                "frame_count": frame_count,
                "duration_seconds": duration_ms / 1000.0,
            }

            # Select frames to process
            selected_frames = [0]
            if frame_count > 10:
                for idx in range(10, frame_count, 10):
                    selected_frames.append(idx)
            else:
                for idx in range(1, frame_count):
                    selected_frames.append(idx)

            captions = []
            ocr_text = ""
            
            # Lazy load transformers/tesseract
            from transformers import BlipForConditionalGeneration, BlipProcessor
            blip_processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
            blip_model = BlipForConditionalGeneration.from_pretrained("Salesforce/blip-image-captioning-base")

            for index, frame_idx in enumerate(selected_frames):
                try:
                    gif.seek(frame_idx)
                    frame_image = gif.convert("RGB")
                    
                    # 1. OCR on the first frame only
                    if frame_idx == 0:
                        try:
                            import pytesseract
                            ocr_text = pytesseract.image_to_string(frame_image).strip()
                        except Exception as ocr_exc:
                            logger.warning("pytesseract OCR failed on GIF first frame: %s", ocr_exc)

                    # 2. Image Captioning for each frame
                    inputs = blip_processor(frame_image, return_tensors="pt")
                    out = blip_model.generate(**inputs, max_new_tokens=50)
                    caption = blip_processor.decode(out[0], skip_special_tokens=True).strip()
                    if caption:
                        captions.append(f"Frame {frame_idx}: {caption}")
                except Exception as frame_exc:
                    logger.warning("Failed to process GIF frame %d: %s", frame_idx, frame_exc)

            # Reset back to 0
            gif.seek(0)

            # Combine all descriptions
            content_parts = []
            if captions:
                content_parts.append("Visual Frame Captions:\n" + "\n".join(captions))
            if ocr_text:
                content_parts.append(f"Extracted Text from First Frame (OCR):\n{ocr_text}")

            content = "\n\n".join(content_parts)

            return {
                "file_name": path.name,
                "content": content,
                "metadata": metadata,
                "file_type": "gif",
            }

        except Exception as exc:
            logger.exception("Failed to process GIF %s", path)
            raise ValueError(f"Could not process GIF file: {path}") from exc
