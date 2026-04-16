# Offer/Quote Extraction Skill

You are extracting data from an offer or quote document.

## Required Fields
- Offer/Quote number
- Date
- Valid until date
- Vendor name and address
- Customer name and address
- Line items (description, quantity, unit price, total)
- Subtotal
- Discount (if any)
- Tax amount and rate
- Total amount
- Delivery terms
- Payment terms
- Validity period

## Rules
- Preserve exact numbers including decimal separators
- If a field is missing, output "NOT FOUND"
- Maintain original language
- Include all line items, never summarize
