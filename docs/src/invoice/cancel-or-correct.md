---
title: "Cancellations & Amendments: cancel or amend an invoice in TaxJar"
description: "Choose between a credit note and a cancellation, cancel an invoice that TaxJar holds, and fix an invoice whose cancellation did not reach TaxJar."
type: "how-to"
---

# Cancellations & Amendments

A submitted invoice is in TaxJar. How you correct it depends on whether TaxJar already filed its period.

## Choose the correction

| The invoice is in… | Do this |
|---|---|
| The current period, not filed yet | Cancel it, then amend it and submit the new invoice. Or make a credit note. |
| A period that TaxJar already filed | Make a [credit note](/invoice/credit-and-debit-notes#make-a-credit-or-debit-note) in the current period. Do not cancel the invoice. |

::: danger Do not cancel an invoice of a filed period
When you cancel an invoice, the app deletes the transaction from TaxJar. This changes the data of a period that is already filed.
:::

Do not change the posting date of a synced invoice.

## Cancel an invoice

1. Open the submitted invoice.
2. Click **Cancel**, then confirm.

The app deletes the transaction from TaxJar in the background. The TaxJar status changes to **Cancelled**.

To correct it, click **Amend**, change what you need, and submit the new invoice. The app sends it to TaxJar as a new transaction.

## If the cancellation did not reach TaxJar

The status is **Failed to Cancel**. The transaction is still in TaxJar.

1. Read the **Sync Error** on the **TaxJar** tab, and fix the cause.
2. Click **TaxJar** → **Sync to TaxJar**, or use **Resync** on the [TaxJar Transaction Sync page](/file/fix-failed-syncs).

For a temporary error, the app also tries again every 15 minutes, up to five times.
