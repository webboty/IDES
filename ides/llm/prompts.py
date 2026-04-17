from __future__ import annotations

DEFAULT_VISION_PROMPT = """Extract ALL text and structure from this document page as Markdown.
Rules:
- Preserve ALL tables using Markdown table syntax (| col1 | col2 |)
- Do NOT add positioning descriptions like (header), (footer), (box rechts)
- Do NOT wrap output in code blocks
- This must be a 100% complete reflection of the document
- Do NOT summarize or omit any content
- Preserve the original language exactly as written
- For numbers: reproduce EXACTLY as shown, including decimal separators
- Include all line items, totals, subtotals, tax amounts"""

DEFAULT_FUSION_PROMPT = """You are a document fusion agent merging multiple extraction sources into accurate Markdown.
CRITICAL RULES:
1. NUMBERS ARE SACRED — every digit, decimal, separator must be exact
2. Cross-validate ALL numbers across sources before including them
3. If sources disagree on a number, silently use the most reliable source (pdfplumber > OCR > vision)
4. Prefer pdfplumber for exact characters (reads digital text layer directly)
5. Prefer vision output for layout and table structure
6. Prefer OCR for exact numbers and text in scanned regions
7. Preserve original document language
8. Do NOT invent content not in any source
9. Output ONLY the clean document Markdown — no commentary, no validation notes, no source references"""

BOILERPLATE_CONFIRM_PROMPT = """A regex pattern flagged this page as potential boilerplate (AGB/terms/legal/impressum).
Is this ENTIRE page boilerplate, or does it contain relevant business data (amounts, dates, line items, order details)?
Content (first 500 chars): {content}
Answer ONE word: RELEVANT (keep it) or BOILERPLATE (skip it)"""

IMAGE_DESCRIBE_PROMPT = (
    "Describe this image from a business document briefly. What is it showing?"
)
