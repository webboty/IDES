from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseExtractor(ABC):
    @abstractmethod
    async def extract(self, pdf_path: str, page_num: int, **kwargs: Any) -> Any: ...
