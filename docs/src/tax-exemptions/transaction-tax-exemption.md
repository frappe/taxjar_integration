---
title: "Transaction Tax Exemption"
description: "Mark one quotation, sales order or sales invoice as exempt when the customer usually pays sales tax, and choose the reason for the exemption."
type: "how-to"
---

# Transaction Tax Exemption

Use this when one sale is exempt, but the customer usually pays tax. For a customer who is always exempt, [exempt the customer](/tax-exemptions/customer-tax-exemption) instead.

::: tip
Get the exemption certificate for this sale from the customer, and keep it. TaxJar and the app do not store certificates.
:::

## Mark a Sale as Exempt

1. Open the quotation, sales order or sales invoice.
2. Below the totals, in **TaxJar Exemptions**, select **Is transaction exempt from sales tax?**.
3. In **Reason for exemption?**, select **Wholesale**, **Government** or **Other**.
4. Save the document.

:::tabs
== Exemption Fields
The **TaxJar Exemptions** section is on the **Details** tab, below the items and the totals.

![A draft Sales Invoice scrolled to the items, the total and the TaxJar Exemptions section with Is transaction exempt from sales tax? selected and the reason Wholesale](/images/invoice-transaction-exempt-section.webp)
== Result
The document has no sales tax. On the **TaxJar** tab, **Is the customer taxable?** shows **Yes, but transaction is marked as exempt**.

![The TaxJar tab of the invoice with the Tax Applicability Matrix, and Is the customer taxable? showing Yes, but transaction is marked as exempt](/images/invoice-transaction-exempt-result.webp)
:::

## Locked Fields

- If the customer has an exemption for the ship-to state, the app fills in these fields and locks them.
- For an export, the app sets the reason to **Other**.

::: warning Exempt sales cannot have sales tax
If the document has a sales tax amount and is marked as exempt, TaxJar does not accept the invoice. Clear the exemption, or remove the sales tax row.
:::
