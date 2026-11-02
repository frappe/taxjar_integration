---
title: "Resolve Failed Syncs"
description: "Find the failed transactions of a period, read each error, fix the cause, and send the transactions to TaxJar again with Resync or Sync to TaxJar."
type: "how-to"
---

# Resolve Failed Syncs

When an invoice or a customer exemption does not reach TaxJar, find it, fix the cause and send it again.

## Pre-requisites

You need write on Sales Invoice, for example the **Accounts User** role. For customers, you also need **Sales User**.

## Resolve a failed sync

::::tabs
== Failed
![The Failed tab of the TaxJar Transaction Sync page with the error popover of one failed invoice](/images/sync-failed-popover.webp)

1. In the TaxJar sidebar, click **TaxJar Transaction Sync**, and click the **Failed** tab.
2. Hover over the information icon in **Sync Status** to read the error. Find it in [Messages & Errors](/help/messages#sync-errors).
3. Fix the cause, select the rows, and click **Resync**.

The rows change to **Queued**, then to **Synced**.

::: tip Temporary errors fix themselves
An error that ends with "Automatic retry is scheduled." is temporary. The app tries again every 15 minutes, up to five times.
:::
== Excluded
**Resync** sends only failed transactions. To send an **Excluded** invoice:

1. Fix the reason, for example turn on sync for the company.
2. Open the invoice, and click **TaxJar** → **Sync to TaxJar**.
== Stuck in Queued
A transaction is usually Queued for less than one minute. If it stays Queued for more than 15 minutes, the background jobs of the server can be stopped. Ask your system administrator to check the background workers.
== Customers
1. On **Customer Tax Exemption**, click **Failed** in the summary strip.
2. Hover over the information icon in **Sync Status** to read the error. Find it in [Messages & Errors](/help/messages#customer-messages).
3. Fix the cause, select the rows, and click **Bulk Action** → **Resync with TaxJar**.

The app also tries a failed customer again every 15 minutes, up to five times. A customer with **Not Sent** waited too long in the queue. Resync it.
::::
