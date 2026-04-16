from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


class FileStore:
    def __init__(self, base_path: str):
        self.base_path = Path(base_path)

    def job_dir(self, job_id: str) -> Path:
        return self.base_path / "jobs" / job_id

    def create_job_dir(self, job_id: str) -> Path:
        jd = self.job_dir(job_id)
        (jd / "pages").mkdir(parents=True, exist_ok=True)
        (jd / "layers").mkdir(parents=True, exist_ok=True)
        (jd / "fusion").mkdir(parents=True, exist_ok=True)
        (jd / "result").mkdir(parents=True, exist_ok=True)
        return jd

    def save_original(
        self, job_id: str, data: bytes, filename: str = "original.pdf"
    ) -> Path:
        path = self.job_dir(job_id) / filename
        path.write_bytes(data)
        return path

    def save_meta(self, job_id: str, meta: dict) -> Path:
        path = self.job_dir(job_id) / "meta.json"
        path.write_text(json.dumps(meta, indent=2))
        return path

    def load_meta(self, job_id: str) -> dict | None:
        path = self.job_dir(job_id) / "meta.json"
        if path.exists():
            return json.loads(path.read_text())
        return None

    def save_classification(self, job_id: str, classifications: list[dict]) -> Path:
        path = self.job_dir(job_id) / "classification.json"
        path.write_text(json.dumps(classifications, indent=2))
        return path

    def load_classification(self, job_id: str) -> list[dict]:
        path = self.job_dir(job_id) / "classification.json"
        if path.exists():
            return json.loads(path.read_text())
        return []

    def save_layer_result(
        self, job_id: str, page_num: int, layer: str, data: Any
    ) -> Path:
        ext = "md" if layer == "vision" else "json"
        fname = f"page_{page_num:03d}_{layer}.{ext}"
        path = self.job_dir(job_id) / "layers" / fname
        if isinstance(data, str):
            path.write_text(data)
        else:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        return path

    def load_layer_result(self, job_id: str, page_num: int, layer: str) -> Any:
        ext = "md" if layer == "vision" else "json"
        fname = f"page_{page_num:03d}_{layer}.{ext}"
        path = self.job_dir(job_id) / "layers" / fname
        if not path.exists():
            return None
        if ext == "json":
            return json.loads(path.read_text())
        return path.read_text()

    def save_fusion_page(self, job_id: str, page_num: int, markdown: str) -> Path:
        path = self.job_dir(job_id) / "fusion" / f"page_{page_num:03d}_merged.md"
        path.write_text(markdown)
        return path

    def load_fusion_page(self, job_id: str, page_num: int) -> str | None:
        path = self.job_dir(job_id) / "fusion" / f"page_{page_num:03d}_merged.md"
        if path.exists():
            return path.read_text()
        return None

    def save_final_result(self, job_id: str, markdown: str, detail: dict) -> Path:
        rdir = self.job_dir(job_id) / "result"
        (rdir / "final.md").write_text(markdown)
        (rdir / "result.json").write_text(
            json.dumps(detail, indent=2, ensure_ascii=False)
        )
        return rdir

    def load_final_markdown(self, job_id: str) -> str | None:
        path = self.job_dir(job_id) / "result" / "final.md"
        if path.exists():
            return path.read_text()
        return None

    def load_result_detail(self, job_id: str) -> dict | None:
        path = self.job_dir(job_id) / "result" / "result.json"
        if path.exists():
            return json.loads(path.read_text())
        return None

    def save_page_pdf(self, job_id: str, page_num: int, data: bytes) -> Path:
        path = self.job_dir(job_id) / "pages" / f"page_{page_num:03d}.pdf"
        path.write_bytes(data)
        return path

    def get_page_images_dir(self, job_id: str, page_num: int) -> Path:
        d = self.job_dir(job_id) / "pages" / f"page_{page_num:03d}_images"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_page_image(
        self, job_id: str, page_num: int, suffix: str, image_bytes: bytes
    ) -> Path:
        path = self.job_dir(job_id) / "pages" / f"page_{page_num:03d}_{suffix}"
        path.write_bytes(image_bytes)
        return path

    def cleanup_job(self, job_id: str) -> None:
        jd = self.job_dir(job_id)
        if jd.exists():
            shutil.rmtree(jd)
