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
3. If sources disagree on a number, state which source you chose and why
4. Prefer pdfplumber for exact characters (reads digital text layer directly)
5. Prefer vision output for layout and table structure
6. Prefer OCR for text in scanned regions
7. Preserve original document language
8. Do NOT invent content not in any source"""

BOILERPLATE_PROMPT = """Is this page relevant business information or boilerplate (terms/legal/AGB/impressum)?
Content (first 500 chars): {content}
Answer ONE word: RELEVANT or BOILERPLATE"""

IMAGE_DESCRIBE_PROMPT = (
    "Describe this image from a business document briefly. What is it showing?"
)
