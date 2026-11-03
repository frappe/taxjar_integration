---
title: "Sales Tax Invoice Print Format"
description: "Print quotations, sales orders, invoices, credit notes and debit notes in the US Sales Tax formats, with the tax for each jurisdiction, or build your own format."
type: "how-to"
---

# Print Format

The app adds three print formats with the TaxJar tax details:

| Document | Print format |
|---|---|
| Quotation | **US Sales Tax Quotation** |
| Sales Order | **US Sales Tax Sales Order** |
| Sales Invoice, credit note and debit note | **US Sales Tax (Invoice, DN, CN)** |

Each format becomes the default print format of its document, and **US Company Letter Head** the default letter head, when none is set.

## Print a Document

1. Open the quotation, sales order, sales invoice, credit note or debit note.
2. Click the print icon.
3. In **Print Format**, select the US Sales Tax format of the document.
4. Click **Print** or **PDF**.

## What the Format Shows

:::tabs
== Quotation
![A Quotation printed in the US Sales Tax Quotation format with the Valid Till date, the Tax Analysis table, the totals and the Terms and Conditions as a list](/images/print-us-sales-tax-quotation.webp)
== Sales Order
![A Sales Order printed in the US Sales Tax Sales Order format with the Delivery Date, the Tax Analysis table, the totals and the Terms and Conditions as a list](/images/print-us-sales-tax-sales-order.webp)
== Sales Invoice
![A Sales Invoice printed in the US Sales Tax (Invoice, DN, CN) format with the Tax Analysis table, the totals, In Words and the Terms and Conditions as a list](/images/print-us-sales-tax-invoice-bullets.webp)
== Credit Note
![A Credit Note printed in the US Sales Tax (Invoice, DN, CN) format with the Sales invoice Ref., the negative amounts, the negative tax for each jurisdiction and the Terms and Conditions as a list](/images/print-us-sales-tax-credit-note-terms.webp)
== Debit Note
![A Debit Note printed in the US Sales Tax (Invoice, DN, CN) format with the Sales invoice Ref., the extra amount, its tax for each jurisdiction and the Terms and Conditions as a list](/images/print-us-sales-tax-debit-note-terms.webp)
:::

| Part | Shows |
|---|---|
| **Title** | The document type, for example **Quotation** or **Credit Note**, with its number. For an export, **EXPORT** shows below the title. |
| **Dates** | **Date**, and **Valid Till** on a quotation, **Delivery Date** on a sales order, or **Due Date** on an invoice. |
| **References** | **Sales invoice Ref.**, the original invoice of a credit note or a debit note. **Purchase Order No.**, when the document has one. |
| **Addresses** | **Ship From**, **Bill To** and **Ship To**, with the company Tax ID and the customer Tax ID. |
| **Items** | The item description below the item name, when it is different from the name. |
| **Tax Analysis** | The tax for each jurisdiction, and the tax status line, for example "Destination-based tax for {ship-to}". With no tax, it shows "Taxes are not applicable". |
| **Totals** | A **Discount** row above **Grand Total**, for a cash or non-trade discount. A trade discount shows in the item **Discount** column. **In Words** shows below **Grand Total**. |
| **Terms and Conditions** | Below the totals, when the document has terms. |

## Build Your Own Format

To change the layout, make your own format from a copy of the app's format:

1. Open the **Print Format** list, and open the US Sales Tax format of the document.
2. In the menu, click **Duplicate**, and give the copy a new name.
3. Change the HTML of the copy.
4. To print with the copy by default, set it as **Default Print Format** of the document in **Customize Form**.

Quotations, sales orders and sales invoices have the same TaxJar fields. The copy can use these fields of the document:

| Field | Holds |
|---|---|
| `doc.taxjar_breakdown_html` | The jurisdiction table. The app fills it in when you print. |
| `doc.taxjar_tax_source` | `origin` or `destination`: the address that sets the rate. |
| `doc.taxjar_ship_to` | The ship-to address that TaxJar used. |
| `doc.taxjar_has_nexus` | `1` when the company has nexus in the ship-to state. |
| `doc.taxjar_customer_taxable` | `0` when the customer is exempt. |
| `doc.taxjar_transaction_exempt` | `1` when the sale is marked as exempt. |
| `doc.taxjar_freight_taxable` | `1` when the state taxes the shipping. |

::: info App updates
App updates change only the app's own format. Your copy keeps your changes, but it does not get the updates of the app's format.
:::
