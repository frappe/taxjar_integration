---
title: "No Sales Tax on a Document: fix missing or wrong sales tax"
description: "Find why a quotation, sales order or sales invoice has no sales tax from TaxJar, with the cause and the fix for each answer on the TaxJar tab."
type: "how-to"
---

# No Sales Tax on a Document

## Find the cause

1. Save the document.
2. Look at the top of the form. A message there gives the cause for the three most common cases.
3. Open the **TaxJar** tab, and read the three cards of the **Tax Applicability Matrix**.
4. Find the cause in the table.

| You see | Cause | Fix |
|---|---|---|
| "Customer address is not set, hence taxes are not calculated." | The document has no address. | Click **Create Address →**, or select a **Shipping Address**. |
| "Nexus not configured for {state}, hence no taxes are charged." Or **Do you have a nexus here?** is **No**. | You have no nexus in the ship-to state. | If you must collect tax there, add the state in TaxJar. Then [update the nexus](/setup/nexus#update-the-nexus-now). |
| "Sales taxes are not applicable on export transactions." | The ship-to country is not the United States. | Nothing. Exports have no US sales tax. |
| **Is the customer taxable?** is **No** | The customer is exempt in the ship-to state. | Check the exemption of the customer. Refer to [Customer Tax Exemption](/sell/exempt-customers). |
| **Is the customer taxable?** is **Yes, but transaction is marked as exempt** | The document is marked as exempt. | Clear **Is transaction exempt from sales tax?**. |
| **Is the product taxable?** is **No** | The state does not tax the items. | Check the **Product Tax Category** of each item. |
| No message, and the TaxJar tab is not there | The company does not calculate tax. | Turn on **Compute Taxes on Sales** for the company in [TaxJar Setup](/setup/guided-setup#features). Make sure that **Enable TaxJar** is on. |
| An orange message: "TaxJar API is unreachable. Tax has not been calculated for this document." | TaxJar did not answer. | Wait, then save the document again. |

## The tax is there, but it looks wrong

- Check the **Ship From** and **Ship To** addresses on the TaxJar tab. A wrong postal code gives a wrong rate. Refer to [Address Validation](/setup/address-validation).
- Check the product tax categories of the items.
- If you changed the items, the address or the shipping, save the document again.
- Open [TaxJar Tax Breakdown](/sell/check-the-tax#check-the-tax) to see the tax for each jurisdiction.

If the save stops with a message, find the message in [Messages & Errors](/help/messages).
