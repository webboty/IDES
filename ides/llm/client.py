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
        self._available: dict[str, bool] = {}
        for name, p in providers.items():
            self._clients[name] = AsyncOpenAI(
                base_url=p["base_url"],
                api_key=p.get("api_key", "not-needed"),
            )
            self._timeouts[name] = p.get("timeout", 120)

    async def check_provider(self, name: str) -> dict:
        client = self._clients.get(name)
        if not client:
            return {"provider": name, "status": "not_configured"}
        timeout = min(self._timeouts.get(name, 120), 10)
        try:
            await asyncio.wait_for(
                client.models.list(),
                timeout=timeout,
            )
            self._available[name] = True
            return {"provider": name, "status": "ok"}
        except asyncio.TimeoutError:
            self._available[name] = False
            return {"provider": name, "status": "timeout"}
        except Exception as e:
            self._available[name] = False
            return {"provider": name, "status": "error", "error": str(e)[:200]}

    async def check_all(self) -> list[dict]:
        results = []
        for name in self._clients:
            results.append(await self.check_provider(name))
        return results

    def is_available(self, provider: str) -> bool:
        return self._available.get(provider, False)

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
            self._available[provider] = False
            raise ExtractionError(f"LLM timeout for model {model_config['name']}")
        except Exception as e:
            self._available[provider] = False
            raise ExtractionError(f"LLM error: {str(e)[:200]}")

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
