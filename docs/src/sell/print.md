---
title: "Sales Tax Invoice Print Format"
description: "Print sales invoices, credit notes and debit notes with the US Sales Tax print format, which shows the tax for each jurisdiction and the tax status line."
type: "how-to"
---

# Print Format

The app adds the print format **US Sales Tax (Invoice, DN, CN)**. It prints sales invoices, debit notes and credit notes with the TaxJar tax details.

## Print the document

![A Sales Invoice printed in the US Sales Tax (Invoice, DN, CN) format with the Tax Analysis table and the totals](/images/print-us-sales-tax-invoice.webp)

1. Open the sales invoice, credit note or debit note.
2. Click the print icon.
3. In **Print Format**, select **US Sales Tax (Invoice, DN, CN)**.
4. Click **Print** or **PDF**.

## What the format shows

- The title of the document: **Credit Note No.** on a credit note, **Debit Note No.** on a debit note, and **EXPORT** below the title for an export.
- **Sales invoice Ref.**: the original invoice of a credit note or a debit note.
- **Purchase Order No.**, when the invoice has one.
- **Ship From**, **Bill To** and **Ship To**, with the company Tax ID and the customer Tax ID.
- The item description below the item name, when it is different from the name.
- **Tax Analysis**: the tax status line, for example "Destination-based tax for {ship-to}", and the tax for each jurisdiction. With no tax, it shows "Taxes are not applicable".
- A **Discount** row above **Grand Total**, for a cash or non-trade discount. A trade discount shows in the item **Discount** column.

## Defaults that the app sets

The format becomes the default print format of Sales Invoice, and **US Company Letter Head** the default letter head, but only when none is set.
