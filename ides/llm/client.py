from __future__ import annotations

import asyncio
import re
from typing import Any

from openai import AsyncOpenAI

from ides.models import ExtractionError


class LLMClient:
    def __init__(self, providers: dict[str, dict]):
        self._clients: dict[str, AsyncOpenAI] = {}
        self._timeouts: dict[str, int] = {}
        for name, p in providers.items():
            self._clients[name] = AsyncOpenAI(
                base_url=p["base_url"],
                api_key=p.get("api_key", "not-needed"),
            )
            self._timeouts[name] = p.get("timeout", 120)

    async def chat(
        self, model_config: dict, messages: list[dict], **kwargs: Any
    ) -> str:
        provider = model_config.get("provider", "local")
        client = self._clients.get(provider)
        if not client:
            raise ExtractionError(f"Unknown provider: {provider}")
        timeout = self._timeouts.get(provider, 120)
        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model_config["name"],
                    messages=messages,
                    max_tokens=model_config.get("max_tokens", 4000),
                    **kwargs,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise ExtractionError(f"LLM timeout for model {model_config['name']}")

        text = response.choices[0].message.content or ""
        return re.sub(r"<think.*?</think\s*>", "", text, flags=re.DOTALL).strip()

    async def chat_with_image(
        self, model_config: dict, b64_image: str, prompt: str, **kwargs: Any
    ) -> str:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64_image}"},
                    },
                ],
            }
        ]
        return await self.chat(model_config, messages, **kwargs)
