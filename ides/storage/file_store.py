from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class FileStore:
    def __init__(self, base_path: str):
        self.base_path = Path(base_path)

    def job_dir(self, storage_path: str) -> Path:
        return self.base_path / storage_path

    def create_job_dir(self, job_id: str, dt: datetime | None = None) -> str:
        if dt is None:
            dt = datetime.now(timezone.utc)
        storage_path = f"jobs/{dt.year}/{dt.month:02d}/{dt.day:02d}/{job_id}/"
        jd = self.job_dir(storage_path)
        (jd / "pages").mkdir(parents=True, exist_ok=True)
        (jd / "layers").mkdir(parents=True, exist_ok=True)
        (jd / "fusion").mkdir(parents=True, exist_ok=True)
        (jd / "result").mkdir(parents=True, exist_ok=True)
        return storage_path

    def save_original(
        self, storage_path: str, data: bytes, filename: str = "original.pdf"
    ) -> Path:
        path = self.job_dir(storage_path) / filename
        path.write_bytes(data)
        return path

    def save_meta(self, storage_path: str, meta: dict) -> Path:
        path = self.job_dir(storage_path) / "meta.json"
        path.write_text(json.dumps(meta, indent=2))
        return path

    def load_meta(self, storage_path: str) -> dict | None:
        path = self.job_dir(storage_path) / "meta.json"
        if path.exists():
            return json.loads(path.read_text())
        return None

    def save_classification(self, storage_path: str, classifications: list[dict]) -> Path:
        path = self.job_dir(storage_path) / "classification.json"
        path.write_text(json.dumps(classifications, indent=2))
        return path

    def load_classification(self, storage_path: str) -> list[dict]:
        path = self.job_dir(storage_path) / "classification.json"
        if path.exists():
            return json.loads(path.read_text())
        return []

    def save_layer_result(
        self, storage_path: str, page_num: int, layer: str, data: Any
    ) -> Path:
        ext = "md" if layer == "vision" else "json"
        fname = f"page_{page_num:03d}_{layer}.{ext}"
        path = self.job_dir(storage_path) / "layers" / fname
        if isinstance(data, str):
            path.write_text(data)
        else:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        return path

    def load_layer_result(self, storage_path: str, page_num: int, layer: str) -> Any:
        ext = "md" if layer == "vision" else "json"
        fname = f"page_{page_num:03d}_{layer}.{ext}"
        path = self.job_dir(storage_path) / "layers" / fname
        if not path.exists():
            return None
        if ext == "json":
            return json.loads(path.read_text())
        return path.read_text()

    def save_fusion_page(self, storage_path: str, page_num: int, markdown: str) -> Path:
        path = self.job_dir(storage_path) / "fusion" / f"page_{page_num:03d}_merged.md"
        path.write_text(markdown)
        return path

    def load_fusion_page(self, storage_path: str, page_num: int) -> str | None:
        path = self.job_dir(storage_path) / "fusion" / f"page_{page_num:03d}_merged.md"
        if path.exists():
            return path.read_text()
        return None

    def save_final_result(self, storage_path: str, markdown: str, detail: dict) -> Path:
        rdir = self.job_dir(storage_path) / "result"
        (rdir / "final.md").write_text(markdown)
        (rdir / "result.json").write_text(
            json.dumps(detail, indent=2, ensure_ascii=False)
        )
        return rdir

    def load_final_markdown(self, storage_path: str) -> str | None:
        path = self.job_dir(storage_path) / "result" / "final.md"
        if path.exists():
            return path.read_text()
        return None

    def load_result_detail(self, storage_path: str) -> dict | None:
        path = self.job_dir(storage_path) / "result" / "result.json"
        if path.exists():
            return json.loads(path.read_text())
        return None

    def save_page_pdf(self, storage_path: str, page_num: int, data: bytes) -> Path:
        path = self.job_dir(storage_path) / "pages" / f"page_{page_num:03d}.pdf"
        path.write_bytes(data)
        return path

    def get_page_images_dir(self, storage_path: str, page_num: int) -> Path:
        d = self.job_dir(storage_path) / "pages" / f"page_{page_num:03d}_images"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_page_image(
        self, storage_path: str, page_num: int, suffix: str, image_bytes: bytes
    ) -> Path:
        path = self.job_dir(storage_path) / "pages" / f"page_{page_num:03d}_{suffix}"
        path.write_bytes(image_bytes)
        return path

    def cleanup_job(self, storage_path: str) -> None:
        jd = self.job_dir(storage_path)
        if jd.exists():
            shutil.rmtree(jd)
