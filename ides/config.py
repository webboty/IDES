from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


def _env_substitute(value: str) -> str:
    import re

    def replacer(match):
        env_var = match.group(1)
        return os.environ.get(env_var, match.group(0))

    return re.sub(r"\$\{(\w+)\}", replacer, value)


def _deep_env_substitute(obj: Any) -> Any:
    if isinstance(obj, str):
        return _env_substitute(obj)
    if isinstance(obj, dict):
        return {k: _deep_env_substitute(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_env_substitute(i) for i in obj]
    return obj


class DPIConfig(BaseModel):
    vision: int = 200
    ocr: int = 300


class ExtractionConfig(BaseModel):
    dpi: DPIConfig = DPIConfig()
    ocr_languages: str = "deu+eng+rus"
    max_pages: int = 50
    skip_boilerplate: bool = True
    boilerplate_patterns: list[str] = Field(default_factory=list)


class ThresholdConfig(BaseModel):
    text_rich: int = 500
    text_moderate: int = 200
    text_sparse: int = 50
    min_image_size: int = 100


class RetryConfig(BaseModel):
    max_attempts: int = 3
    backoff_base: int = 5


class QueueConfig(BaseModel):
    max_concurrent_jobs: int = 2
    job_timeout: int = 600
    worker_poll_interval: int = 2


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    master_admin_key: str = ""


class StorageConfig(BaseModel):
    base_path: str = "./data"


class ProviderConfig(BaseModel):
    base_url: str = ""
    api_key: str = ""
    timeout: int = 120


class ModelConfig(BaseModel):
    provider: str = "local"
    name: str = ""
    max_tokens: int = 4000


class ModelsConfig(BaseModel):
    vision: ModelConfig = ModelConfig()
    merge: ModelConfig = ModelConfig()
    filter: ModelConfig = ModelConfig()
    image_describe: ModelConfig = ModelConfig()


class AppConfig(BaseSettings):
    server: ServerConfig = ServerConfig()
    storage: StorageConfig = StorageConfig()
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    models: ModelsConfig = ModelsConfig()
    extraction: ExtractionConfig = ExtractionConfig()
    thresholds: ThresholdConfig = ThresholdConfig()
    retry: RetryConfig = RetryConfig()
    queue: QueueConfig = QueueConfig()

    model_config = {"extra": "ignore"}


def load_config(config_path: str | Path = "config.yaml") -> AppConfig:
    config_path = Path(config_path)
    if config_path.exists():
        with open(config_path) as f:
            raw = yaml.safe_load(f)
        raw = _deep_env_substitute(raw)
    else:
        raw = {}
    return AppConfig(**raw)


_config: AppConfig | None = None


def get_config() -> AppConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config
