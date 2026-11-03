---
title: "Credit & Debit Notes"
description: "Make a credit note to give money back or a debit note to charge more. Both get sales tax on save and go to TaxJar on submit, with different rules."
type: "how-to"
---

# Credit & Debit Notes

A credit note gives money back on an earlier sales invoice, and a debit note charges more on it. In ERPNext, both are sales invoices: they get sales tax when you save them, and go to TaxJar when you submit them.

| | Credit Note | Debit Note |
|---|---|---|
| **Use it to** | Give money back, for example for a return | Charge more, for example after a price increase |
| **In TaxJar** | <Badge type="warning" text="TaxJar Refund" /> against the original invoice | <Badge type="tip" text="TaxJar Order" /> a new order |
| **Original invoice** | Must be **Synced** first | No rule |

## Credit Note

TaxJar records a credit note as a refund of the original invoice, so you always make the credit note from the original invoice.

::: tip
The original invoice must have the TaxJar status **Synced**. If it is **Failed** or **Excluded**, [send it to TaxJar](/transaction-sync/syncing-to-taxjar#resync-an-invoice) first.
:::

::::tabs
== From the Invoice
1. Open the original sales invoice.
2. Click **Create** → **Return / Credit Note**.
3. Change the items and the quantities to the returned values.
4. Save and submit the credit note.

The app sends the credit note to TaxJar as a refund.

![A submitted Sales Invoice with the Create menu open and Return / Credit Note in the list](/images/credit-note-create-menu.webp)
== From a New Invoice
If you select **Is Return (Credit Note)** on a new sales invoice, the dialog **Credit Note Against Invoice** opens.

![A new Sales Invoice with Is Return (Credit Note) selected in the Details tab](/images/new-invoice-is-return.webp)

1. Select the **Customer**.
2. Select the original **Sales Invoice**. The preview shows its **Sync Status**, which must be **Synced**.
3. Click **Continue**.

The app opens a new credit note against that invoice. If you close the dialog, the app clears **Is Return (Credit Note)**.

![The Credit Note Against Invoice dialog with a synced invoice selected and its preview](/images/dialog-credit-note-against-invoice.webp)
== Errors
The app stops the credit note with one of these messages.

::: warning Original Invoice Not Synced
The original invoice is not in TaxJar. Send the original invoice to TaxJar, then submit the credit note.
:::

::: warning TaxJar: Missing Return Reference
The credit note does not name its original invoice. Make it from the original invoice with **Create** → **Return / Credit Note**.
:::

::: warning {customer} has no submitted invoice.
The customer has no invoice to credit. Submit an invoice for the customer first.
:::
== Exports
If the company sends domestic sales only, an export invoice is **Excluded**. You can make a credit note for it. The credit note is also **Excluded**, and nothing goes to TaxJar.
::::

## Debit Note

A debit note adds an amount to an earlier sales invoice. In ERPNext, it is a sales invoice with **Is Rate Adjustment Entry (Debit Note)** set. The app treats it like a sales invoice:

- When you save it, TaxJar calculates the sales tax on the added amount.
- When you submit it, the app sends it to TaxJar as a new order. The original invoice in TaxJar does not change.

:::tabs
== Make the Debit Note
1. Make a new **Sales Invoice** for the same company and customer as the original invoice.
2. Select **Is Rate Adjustment Entry (Debit Note)**.
3. In **Return Against**, select the original invoice. After you save, ERPNext shows this field as **Adjustment Against**.
4. In the items table, enter the added amount as the rate of each item.
5. Save the debit note, and check the **Sales Tax** row in the taxes table.
6. Submit the debit note.

![A new Sales Invoice with Is Rate Adjustment Entry (Debit Note) selected and the original invoice in Return Against](/images/new-invoice-debit-note.webp)
== Check the Sync
Open the **TaxJar** tab of the debit note. **TaxJar Sync Status** shows **Queued**, then **Synced**, usually in less than a minute. If it shows **Failed**, refer to [Resolve Failed Syncs](/transaction-sync/resolve-failed-syncs).

On the **TaxJar Transaction Sync** page, filter by the transaction type **Debit Note** to see all debit notes.
:::
