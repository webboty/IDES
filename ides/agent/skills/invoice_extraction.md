# Invoice Extraction Skill

You are extracting data from an invoice document.

## Required Fields
- Invoice number
- Invoice date
- Due date
- Vendor name and address
- Customer name and address
- Line items (description, quantity, unit price, total)
- Subtotal
- Tax amount and rate
- Total amount
- Payment terms
- Bank details (IBAN, BIC, bank name)

## Rules
- Preserve exact numbers including decimal separators
- If a field is missing, output "NOT FOUND"
- Maintain original language
- Include all line items, never summarize
