import os
import sys
import json
import base64
import hashlib
import numpy as np
from pathlib import Path


def detect_and_encode(image_path: str) -> dict:
   
    image_path = str(Path(image_path).resolve())
    if not os.path.isfile(image_path):
        return {
            "face_detected": False,
            "encoding": [],
            "encoding_hash": "",
            "face_location": {},
            "model": "arcface",
            "error": f"File not found: {image_path}",
        }

    try:
        from deepface import DeepFace
    except ImportError as e:
        return {
            "face_detected": False,
            "encoding": [],
            "encoding_hash": "",
            "face_location": {},
            "model": "arcface",
            "error": f"deepface import error: {e}",
        }

    try:
        embeddings = DeepFace.represent(
            img_path=image_path,
            model_name="ArcFace",
            detector_backend="retinaface",
            enforce_detection=True,
            align=True,
        )

        if not embeddings:
            # Fallback: try without enforcement
            embeddings = DeepFace.represent(
                img_path=image_path,
                model_name="ArcFace",
                detector_backend="retinaface",
                enforce_detection=False,
                align=True,
            )

        if not embeddings:
            return {
                "face_detected": False,
                "encoding": [],
                "encoding_hash": "",
                "face_location": {},
                "model": "arcface",
                "error": "No face found in image",
            }

        emb = embeddings[0]
        encoding_list = emb["embedding"]
        facial_area = emb.get("facial_area", {})

        enc_bytes = np.array(encoding_list, dtype=np.float32).tobytes()
        enc_hash = hashlib.sha256(enc_bytes).hexdigest()

        return {
            "face_detected": True,
            "encoding": encoding_list,
            "encoding_hash": enc_hash,
            "face_location": {
                "x": facial_area.get("x", 0),
                "y": facial_area.get("y", 0),
                "w": facial_area.get("w", 0),
                "h": facial_area.get("h", 0),
            },
            "model": "arcface",
            "error": None,
        }

    except ValueError as ve:
        return {
            "face_detected": False,
            "encoding": [],
            "encoding_hash": "",
            "face_location": {},
            "model": "arcface",
            "error": str(ve),
        }
    except Exception as e:
        return {
            "face_detected": False,
            "encoding": [],
            "encoding_hash": "",
            "face_location": {},
            "model": "arcface",
            "error": f"Detection failed: {e}",
        }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python detector.py <image_path>")
        sys.exit(1)
    result = detect_and_encode(sys.argv[1])
    print(json.dumps(result, indent=2))
