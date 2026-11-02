---
title: "Credit & Debit Notes"
description: "Make a credit note to give money back or a debit note to charge more. Both get sales tax on save and go to TaxJar on submit, with different rules."
type: "how-to"
---

# Credit & Debit Notes

A credit note gives money back on an earlier sales invoice. A debit note charges more on an earlier sales invoice. In ERPNext, both are sales invoices. Both get sales tax when you save them, and both go to TaxJar when you submit them.

| | Credit note | Debit note |
|---|---|---|
| Use it to | Give money back, for example for a return | Charge more, for example after a price increase |
| In TaxJar | A refund against the original invoice | A new order |
| The original invoice | Must be synced first | Has no rule |

## Make a credit or debit note

::::tabs
== Credit Notes
TaxJar records a credit note as a refund of the original invoice. So you always make the credit note from the original invoice.

**Pre-requisites**

The original invoice must have the TaxJar status **Synced**. If it is **Failed** or **Excluded**, [send it to TaxJar](/invoice/how-sync-works#send-one-invoice-again) first.

**Make the credit note from the invoice**

1. Open the original sales invoice.
2. Click **Create** → **Return / Credit Note**.
3. Change the items and the quantities to the returned values.
4. Save and submit the credit note.

![A submitted Sales Invoice with the Create menu open and Return / Credit Note in the list](/images/credit-note-create-menu.webp)

The app sends the credit note to TaxJar as a refund.

**Make the credit note from a new invoice**

If you select **Is Return (Credit Note)** on a new sales invoice, the dialog **Credit Note Against Invoice** opens.

1. Select the **Customer**.
2. Select the original **Sales Invoice**. The preview shows its **Sync Status**. It must be **Synced**.
3. Click **Continue**.

![The Credit Note Against Invoice dialog with a synced invoice selected and its preview](/images/dialog-credit-note-against-invoice.webp)

The app opens a new credit note against that invoice. If you close the dialog, the app clears **Is Return (Credit Note)**.

**If the app stops the credit note**

| Message | Cause | What to do |
|---|---|---|
| **Original Invoice Not Synced** | The original invoice is not in TaxJar. | Send the original invoice to TaxJar. Then submit the credit note. |
| **TaxJar: Missing Return Reference** | The credit note does not name its original invoice. | Make it from the original invoice with **Create** → **Return / Credit Note**. |
| "{customer} has no submitted invoice." | The customer has no invoice to credit. | Submit an invoice for the customer first. |

**Exports**

If the company sends domestic sales only, an export invoice is **Excluded**. You can make a credit note for it. The credit note is also **Excluded**, and nothing goes to TaxJar.
== Debit Notes
A debit note adds an amount to an earlier sales invoice, for example after a price increase. In ERPNext, a debit note is a sales invoice with **Is Rate Adjustment Entry (Debit Note)** set.

The app treats a debit note like a sales invoice:

- When you save it, TaxJar calculates the sales tax on the added amount.
- When you submit it, the app sends it to TaxJar as a new order. The original invoice in TaxJar does not change.

**Make the debit note**

1. Make a new **Sales Invoice** for the same company and customer as the original invoice.
2. Select **Is Rate Adjustment Entry (Debit Note)**.
3. In **Adjustment Against**, select the original invoice.
4. In the items table, enter the added amount as the rate of each item.
5. Save the debit note. Check the **Sales Tax** row in the taxes table.
6. Submit the debit note.

**Check that TaxJar received it**

Open the **TaxJar** tab of the debit note. **TaxJar Sync Status** shows **Queued**, then **Synced**, usually in less than a minute. If it shows **Failed**, refer to [Resolve Failed Syncs](/file/fix-failed-syncs).

On the **TaxJar Transaction Sync** page, filter by the transaction type **Debit Note** to see all debit notes.
::::
