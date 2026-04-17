from __future__ import annotations

import json
import re
from typing import Any

from ides.llm.client import LLMClient
from ides.llm.prompts import DEFAULT_FUSION_PROMPT


def normalize_number(num_str: str) -> str:
    cleaned = num_str.strip()
    cleaned = cleaned.replace("€", "").replace("$", "").replace(" ", "")
    return cleaned


def extract_numbers(text: str) -> list[str]:
    pattern = r"[\d\.,]+\d{2}"
    return re.findall(pattern, text)


def validate_numbers(sources: dict[str, str]) -> dict[str, dict]:
    all_numbers: dict[str, dict] = {}

    for source_name, content in sources.items():
        if not content:
            continue
        found = extract_numbers(content)
        for num in found:
            normalized = normalize_number(num)
            if normalized not in all_numbers:
                all_numbers[normalized] = {"sources": {}}
            all_numbers[normalized]["sources"][source_name] = num

    results: dict[str, dict] = {}
    for num, info in all_numbers.items():
        source_values = list(info["sources"].values())
        sources_agree = len(set(source_values)) == 1
        confidence = "high" if sources_agree else "medium"

        if "text_layer" in info["sources"]:
            recommended = info["sources"]["text_layer"]
            confidence = "high"
        elif "ocr" in info["sources"]:
            recommended = info["sources"]["ocr"]
            num_sources = len(info["sources"])
            if num_sources == 1:
                confidence = "medium"
        else:
            recommended = source_values[0]
            confidence = "low"

        results[num] = {
            "sources": info["sources"],
            "confidence": confidence,
            "recommended": recommended,
        }

    return results


class FusionAgent:
    def __init__(
        self,
        llm_client: LLMClient,
        model_config: dict,
        system_prompt: str | None = None,
    ):
        self.llm_client = llm_client
        self.model_config = model_config
        self.system_prompt = system_prompt or DEFAULT_FUSION_PROMPT

    async def fuse_page(
        self,
        page_num: int,
        layer_results: dict[str, Any],
    ) -> str:
        vision_md = ""
        if "vision" in layer_results and layer_results["vision"]:
            vision_md = (
                layer_results["vision"].get("markdown", "N/A")
                if isinstance(layer_results["vision"], dict)
                else str(layer_results["vision"])
            )

        text_layer_text = "N/A"
        text_layer_tables = "N/A"
        if "text_layer" in layer_results and layer_results["text_layer"]:
            tl = layer_results["text_layer"]
            if isinstance(tl, dict):
                text_layer_text = tl.get("text", "N/A")
                text_layer_tables = tl.get("markdown", "N/A")
            else:
                text_layer_text = str(tl)

        ocr_text = "N/A"
        if "ocr" in layer_results and layer_results["ocr"]:
            oc = layer_results["ocr"]
            if isinstance(oc, dict):
                ocr_text = oc.get("text", "N/A")
            else:
                ocr_text = str(oc)

        sources = {}
        if text_layer_text != "N/A":
            sources["text_layer"] = text_layer_text
        if ocr_text != "N/A":
            sources["ocr"] = ocr_text
        if vision_md != "N/A":
            sources["vision"] = vision_md

        number_report = validate_numbers(sources) if len(sources) > 1 else {}

        number_section = ""
        if number_report:
            number_section = (
                f"\n\nNUMBER VALIDATION REPORT:\n{json.dumps(number_report, indent=2)}"
            )

        user_msg = (
            f"Merge these extraction sources for page {page_num}:\n\n"
            f"VISION STRUCTURE:\n{vision_md}\n\n"
            f"PDFPLUMBER TEXT:\n{text_layer_text}\n\n"
            f"PDFPLUMBER TABLES:\n{text_layer_tables}\n\n"
            f"OCR TEXT:\n{ocr_text}\n\n"
            f"{number_section}\n\n"
            f"Cross-validate ALL numbers. Resolve any conflicts. Output clean Markdown."
        )

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_msg},
        ]

        result = await self.llm_client.chat(self.model_config, messages)
        return result

    async def analyze_failure(
        self,
        error: str,
        retry_history: list[dict] | None = None,
        classifications: list[dict] | None = None,
    ) -> dict:
        user_msg = (
            f"Analyze this extraction failure and suggest a recovery plan:\n\n"
            f"ERROR: {error}\n\n"
            f"RETRY HISTORY: {json.dumps(retry_history or [])}\n\n"
            f"PAGE CLASSIFICATIONS: {json.dumps(classifications or [])}\n\n"
            f"Return a JSON object with: diagnosis, adjusted_plan, confidence"
        )

        messages = [
            {
                "role": "system",
                "content": "You are a document extraction recovery agent. Analyze failures and suggest adjustments. Always respond with valid JSON.",
            },
            {"role": "user", "content": user_msg},
        ]

        try:
            response = await self.llm_client.chat(self.model_config, messages)
            return json.loads(response)
        except (json.JSONDecodeError, Exception) as e:
            return {
                "diagnosis": f"Agent analysis failed: {e}",
                "adjusted_plan": None,
                "confidence": 0.0,
                "explanation": str(e),
            }
