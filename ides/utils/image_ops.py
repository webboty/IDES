from __future__ import annotations

import io

import cv2
import numpy as np
from PIL import Image


def preprocess_for_ocr(image_bytes: bytes) -> bytes:
    image = Image.open(io.BytesIO(image_bytes))
    img_array = np.array(image)
    if len(img_array.shape) == 3:
        gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    else:
        gray = img_array
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    kernel = np.ones((1, 1), np.uint8)
    dilated = cv2.dilate(thresh, kernel, iterations=1)
    result = Image.fromarray(dilated)
    buf = io.BytesIO()
    result.save(buf, format="PNG")
    return buf.getvalue()


def image_to_grayscale(image_bytes: bytes) -> bytes:
    image = Image.open(io.BytesIO(image_bytes))
    gray = image.convert("L")
    buf = io.BytesIO()
    gray.save(buf, format="PNG")
    return buf.getvalue()
