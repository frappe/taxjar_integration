---
title: "Missing Sales Tax"
description: "Find why a quotation, sales order or sales invoice has no sales tax from TaxJar, with the cause and the fix for each answer on the TaxJar tab."
type: "how-to"
---

# Missing Sales Tax

When a quotation, sales order or sales invoice has no sales tax, the form or the **TaxJar** tab tells you why.

## Find the Cause

1. Save the document.
2. Look at the top of the form. A message there gives the cause for the three most common cases.
3. If there is no message, open the **TaxJar** tab, and read the three cards of the **Tax Applicability Matrix**.

::::tabs
== Form Message
| Message | Cause | Fix |
|---|---|---|
| "Customer address is not set, hence taxes are not calculated." | The document has no address. | Click **Create Address →**, or select a **Shipping Address**. |
| "Nexus not configured for {state}, hence no taxes are charged." | You have no nexus in the ship-to state. | If you must collect tax there, add the state in TaxJar. Then [sync the nexus](/setting-up/updating-your-nexus#on-demand-nexus-sync). |
| "Sales taxes are not applicable on export transactions." | The ship-to country is not the United States. | Nothing. Exports have no US sales tax. |
| "TaxJar API is unreachable. Tax has not been calculated for this document." (orange) | TaxJar did not answer. | Wait, then save the document again. |
== TaxJar Tab
| Card | Answer | Cause | Fix |
|---|---|---|---|
| **Do you have a nexus here?** | <Badge type="danger" text="No" /> | You have no nexus in the ship-to state. | Add the state in TaxJar, then [sync the nexus](/setting-up/updating-your-nexus#on-demand-nexus-sync). |
| **Is the customer taxable?** | <Badge type="danger" text="No" /> | The customer is exempt in the ship-to state. | Check the exemption of the customer. Refer to [Customer Tax Exemption](/tax-exemptions/customer-tax-exemption). |
| | <Badge type="warning" text="Yes, but transaction is marked as exempt" /> | The document is marked as exempt. | Clear **Is transaction exempt from sales tax?**. |
| **Is the product taxable?** | <Badge type="danger" text="No" /> | The state does not tax the items. | Check the **Product Tax Category** of each item. |
== No Message
If there is no message, and the **TaxJar** tab is not there, the company does not calculate tax.

1. In [TaxJar Setup](/setting-up/guided-setup#features), turn on **Compute Taxes on Sales** for the company.
2. Make sure that **Enable TaxJar** is on.
::::

## Wrong Tax Amount

If the tax is there but looks wrong, check these:

- The **Ship From** and **Ship To** addresses on the **TaxJar** tab. A wrong postal code gives a wrong rate. Refer to [Address Validation](/setting-up/address-validation).
- The product tax categories of the items.
- The tax for each jurisdiction, in [TaxJar Tax Breakdown](/sales-tax/verify-tax-applicability).

::: tip
If you changed the items, the address or the shipping, save the document again. If the save stops with a message, find it in [Messages & Errors](/troubleshoot/messages-and-errors).
:::
