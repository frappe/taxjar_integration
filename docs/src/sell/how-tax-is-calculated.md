---
title: "Tax Computation: how sales tax is computed on ERPNext documents"
description: "When TaxJar calculates the tax, the data that it uses, why a document can have no tax, and what happens when a quotation becomes an order and an invoice."
type: "explanation"
---

# Tax Computation

When you save a quotation, a sales order, a sales invoice, a credit note or a debit note, the app sends the document data to TaxJar. TaxJar returns the sales tax. The app puts it in the **Sales Tax** row of the taxes table. If the data did not change since the last calculation, the app keeps the tax. Refer to [When the app keeps the tax](#when-the-app-keeps-the-tax).

You do not click a button. Any user who can save the document gets the tax.

## Which documents get tax and which go to TaxJar

All five sales documents get sales tax when you save them. Only sales invoices, and their two variants, credit notes and debit notes, go to TaxJar when you submit them.

| Document | Sales tax on save | Sent to TaxJar on submit |
|---|---|---|
| Quotation | Yes | No |
| Sales Order | Yes | No |
| Sales Invoice | Yes | Yes, as an order |
| Credit Note | Yes | Yes, as a refund |
| Debit Note | Yes | Yes, as an order |

The sync is in [Syncing to TaxJar](/invoice/how-sync-works).

## The data that TaxJar uses

| Data | Comes from |
|---|---|
| Ship from | The company address with **Preferred Billing Address** set. TaxJar Setup sets it. |
| Ship to | The **Shipping Address** of the document. If it is empty, the **Billing Address**. |
| Items | The rate, the quantity and the discount of each item row. |
| Product tax category | The **Product Tax Category** of each item. Refer to [Item Tax Exemption](/setup/product-tax-categories). |
| Shipping | The rows on the company's shipping ledger account. |
| Other charges and discounts | The other rows of the taxes table. Refer to [Additional Charges & Discounts](/sell/extra-charges). |
| Exemption | The exemption of the customer, or of the document. |
| Currency | A document in another currency is converted to USD with the ERPNext exchange rate. TaxJar's answer is converted back. |

## Three questions decide the tax

TaxJar charges sales tax only when all three answers are yes. The **TaxJar** tab of the document shows the three answers. Refer to [Verify Tax Applicability](/sell/check-the-tax).

1. **Do you have nexus in the ship-to state?** If not, no tax.
2. **Is the customer taxable?** An exempt customer, or a sale marked as exempt, pays no tax.
3. **Is the product taxable?** The state may not tax the product tax category of an item.

The state also decides where the rate comes from:

- **Origin-based tax**: the rate of the ship-from address.
- **Destination-based tax**: the rate of the ship-to address.

## When the app does not ask TaxJar

| Case | Result |
|---|---|
| The ship-to country is not the United States | An export. No US sales tax. |
| The document has no address | No tax. The form asks for an address. |
| The company does not calculate tax | No tax. **Compute Taxes on Sales** is off for the company in TaxJar Setup, or TaxJar is off for the site. |
| TaxJar cannot be reached | The document saves without new tax, with an orange message. Save it again later. |

Every message and its fix is in [Messages & Errors](/help/messages).

## When the app keeps the tax

The app keeps the sales tax that is on the document, and does not ask TaxJar again, when all of these are true:

- The data that TaxJar uses did not change. Refer to [The data that TaxJar uses](#the-data-that-taxjar-uses).
- The app calculated the tax in the current calendar month.
- Nobody saved TaxJar Setup after the calculation.
- The **Sales Tax** row is still in the taxes table, with the amount that TaxJar calculated. If you change the amount, or add a second row on the sales tax account, the app asks TaxJar again.

If one of these is not true, the app asks TaxJar again when you save the document.

The month rule is there because TaxJar always uses the rates of the day of the request. Most states and cities change rates on the first day of a month. In a new month, the app asks TaxJar again to get the current rates.

## From quotation to order to invoice

When you make a sales order from a quotation, or an invoice from an order, the new document gets the tax of the source document. If the data is the same and the month is the same, the app keeps that tax. One sale then needs one request to TaxJar.

The app asks TaxJar again for the new document in these cases:

- You changed the items, the quantities, the prices, the addresses, the shipping or the exemption.
- You invoiced only a part of the order.
- The new document is saved in a different month from the calculation.

::: tip Save again after a change
If you change the items, the address or the shipping amount, save the document again. The app then gets a new sales tax from TaxJar.
:::

