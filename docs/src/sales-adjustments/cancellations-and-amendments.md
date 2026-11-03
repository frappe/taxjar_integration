---
title: "Invoice Cancellations & Amendments"
description: "Choose between a credit note and a cancellation, cancel an invoice that TaxJar holds, and fix an invoice whose cancellation did not reach TaxJar."
type: "how-to"
---

# Cancellations & Amendments

A submitted invoice is in TaxJar, so how you correct it depends on whether TaxJar already filed its period.

## Correct an Invoice

::::tabs
== Period Not Filed
The invoice is in the current period, and TaxJar has not filed it yet. Cancel and amend the invoice, or make a [credit note](/sales-adjustments/credit-and-debit-notes#credit-note).

To cancel and amend the invoice:

1. Open the submitted invoice.
2. Click **Cancel**, then confirm. The app deletes the transaction from TaxJar in the background, and the TaxJar status changes to <Badge type="info" text="Cancelled" />.
3. Click **Amend**, change what you need, and submit the new invoice. The app sends it to TaxJar as a new transaction.
== Period Filed
TaxJar already filed the period of the invoice. Make a [credit note](/sales-adjustments/credit-and-debit-notes#credit-note) in the current period.

::: danger Do not cancel an invoice of a filed period
When you cancel an invoice, the app deletes the transaction from TaxJar. This changes the data of a period that is already filed.
:::
::::

::: warning Do not change the posting date of a synced invoice
TaxJar records the transaction on the posting date, so a new date moves the sale to another period.
:::

## Failed Cancellation

If the status is <Badge type="danger" text="Failed to Cancel" />, the app could not delete the transaction, and it is still in TaxJar.

1. Read the **Sync Error** on the **TaxJar** tab, and fix the cause.
2. Click **TaxJar** → **Sync to TaxJar**, or use **Resync** on the **TaxJar Transaction Sync** page. Refer to [Resolve Failed Syncs](/transaction-sync/resolve-failed-syncs).

::: info Temporary errors
For a temporary error, the app also tries again every 15 minutes, up to five times.
:::
