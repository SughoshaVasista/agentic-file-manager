"""Image content extraction using PIL (Pillow), pytesseract (OCR), and BLIP."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from services.processors.base import ExtractedDocument

logger = logging.getLogger(__name__)


class ImageProcessor:
    """Extracts text via OCR and describes image contents using BLIP."""

    supported_extensions = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

    def process(self, file_path: Path | str) -> ExtractedDocument:
        """Extract text and caption from image."""
        path = Path(file_path)
        try:
            # Lazy imports
            from PIL import Image
            from transformers import BlipForConditionalGeneration, BlipProcessor
            
            logger.info("Processing image file: %s", path)
            img = Image.open(path)

            metadata = {
                "dimensions": f"{img.width}x{img.height}",
                "format": img.format,
                "color_mode": img.mode,
            }

            # 1. OCR (pytesseract)
            ocr_text = ""
            try:
                import pytesseract
                ocr_text = pytesseract.image_to_string(img).strip()
            except Exception as ocr_exc:
                logger.warning("pytesseract OCR failed or not configured for image %s: %s", path, ocr_exc)

            # 2. Image Captioning (BLIP)
            caption = ""
            try:
                blip_processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
                blip_model = BlipForConditionalGeneration.from_pretrained("Salesforce/blip-image-captioning-base")
                
                # Ensure image is in RGB mode for BLIP
                rgb_img = img.convert("RGB")
                inputs = blip_processor(rgb_img, return_tensors="pt")
                out = blip_model.generate(**inputs, max_new_tokens=50)
                caption = blip_processor.decode(out[0], skip_special_tokens=True).strip()
            except Exception as blip_exc:
                logger.warning("BLIP caption generation failed for image %s: %s", path, blip_exc)

            # Combine OCR text and caption
            content_parts = []
            if caption:
                content_parts.append(f"Visual Description: {caption}")
            if ocr_text:
                content_parts.append(f"Extracted Text (OCR):\n{ocr_text}")
            
            content = "\n\n".join(content_parts)

            return {
                "file_name": path.name,
                "content": content,
                "metadata": metadata,
                "file_type": "image",
            }

        except Exception as exc:
            logger.exception("Failed to process image %s", path)
            raise ValueError(f"Could not process image file: {path}") from exc
