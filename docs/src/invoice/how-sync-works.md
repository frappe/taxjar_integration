---
title: "Syncing to TaxJar: send sales invoices, credit and debit notes"
description: "Send sales invoices, credit and debit notes to TaxJar on submit, check the sync status, see why some are excluded, and send a failed one again."
type: "how-to"
---

# Syncing to TaxJar

TaxJar AutoFile files your returns from the transactions in your TaxJar account. The app puts your transactions there: when you submit a sales invoice, a credit note or a debit note, the app sends it to TaxJar. This is the **sync**.

Quotations and sales orders get sales tax, but the app does not send them to TaxJar. Refer to [Tax Computation](/sell/how-tax-is-calculated).

## Pre-requisites

- The company has **Sync Transactions to TaxJar** on. Refer to [the Features step of TaxJar Setup](/setup/guided-setup#features).
- The invoice has a **Shipping Address** or a **Billing Address**. Without one, the app does not let you submit.

## What each action does in TaxJar

| Action in ERPNext | Result in TaxJar |
|---|---|
| Save a draft | Nothing. TaxJar gets only submitted documents. |
| Submit a sales invoice | The app makes an order. |
| Submit a debit note | The app makes an order. |
| Submit a credit note | The app makes a refund against the original invoice. |
| Cancel a document | The app deletes the order or the refund. |
| Amend a cancelled invoice and submit it | The amended invoice is a new order, with its own number. |

TaxJar records the transaction on the **Posting Date**. The invoice number is the transaction ID in TaxJar.

## Submit the invoice

1. Open the draft sales invoice.
2. Click **Submit**, then confirm.

The app sends the invoice in the background. The sidebar shows **TaxJar Status**. Hover over the status to see when the app sent the invoice.

![The sidebar of a submitted Sales Invoice with the green Synced status and its hover card](/images/invoice-sidebar-status.webp)

The **TaxJar** tab of a submitted invoice also has a **Transaction Sync** section:

- **Sync Status**: Excluded, Queued, Synced or Failed.
- **Sync Error**: the cause of a failure. It shows only for Failed.
- **Exclusion Reason**: why the app did not send the invoice. It shows only for Excluded.
- **Last Synced**: the time of the last successful sync. A later failure does not clear it.

![The Transaction Sync section of a submitted Sales Invoice with the status Synced and the Last Synced time](/images/invoice-transaction-sync.webp)

The meaning of each status is in [Sync statuses](#sync-statuses). The **Sync Status** column also shows in the Sales Invoice list.

## The sync runs in the background

When you submit, the status changes to **Queued**. In less than a minute, it usually changes to **Synced**. All statuses are in [Sync statuses](#sync-statuses).

## Why an invoice is not sent

The app does not send some invoices. Their status is **Excluded**, with a reason. For example:

- the company has **Domestic only** selected, and the invoice is an export;
- sync was not on for the company, or TaxJar was off, when you submitted the invoice;
- the invoice is from TaxJar version 15, and waits for the upgrade check.

All reasons are in [Sync statuses](#sync-statuses), in the **Exclusion Reasons** tab.

## When TaxJar does not accept an invoice

The status is **Failed**, and the **Sync Error** gives the cause. There are two types of errors:

- **Temporary errors**, for example TaxJar is offline or the rate limit is reached. The error ends with "Automatic retry is scheduled." The app tries again every 15 minutes, up to five times.
- **Errors in the data**, for example an address that TaxJar cannot find. You fix the data, then send the invoice again.

Refer to [Resolve Failed Syncs](/file/fix-failed-syncs).

## Send one invoice again

Use this for an invoice with the status **Failed** or **Excluded**.

1. Fix the cause. The **Sync Error** or the **Exclusion Reason** tells you what to fix. Refer to [Messages & Errors](/help/messages#sync-errors).
2. Click **TaxJar** → **Sync to TaxJar**.
3. Wait for the message "Sync complete".

The button does not show for an export that the company does not send, or for a version 15 invoice that waits for the upgrade check.

To send many failed invoices at one time, use [Resolve Failed Syncs](/file/fix-failed-syncs).

## Why the original invoice matters

TaxJar records a refund against the original order. So a credit note must name its original invoice, and that invoice must be in TaxJar. Refer to [Credit notes](/invoice/credit-and-debit-notes#make-a-credit-or-debit-note).

## Sync statuses

The sync status tells you whether a document is in TaxJar. It shows as **TaxJar Status** in the sidebar of the form, as **Sync Status** on the TaxJar tab, and in the TaxJar Transaction Sync page.

:::tabs
== Invoice Statuses
| Status | Meaning | What to do |
|---|---|---|
| **Submit to Sync** | The document is a draft. | Submit it to send it. |
| **Queued** | The app sends the document now. | Wait. It usually takes less than one minute. |
| **Synced** | The document is in TaxJar. Hover to see when it was sent. | Nothing. |
| **Failed** | TaxJar did not accept the document. Hover to read the error. | [Fix it](/file/fix-failed-syncs). |
| **Excluded** | The app did not send the document. Hover to read the reason. | Check the reason in the **Exclusion Reasons** tab. |
| **Cancelled** | You cancelled the document, and the app deleted it from TaxJar. | Nothing. |
| **Failed to Cancel** | You cancelled the document, but the app could not delete it from TaxJar. | [Fix the cancellation](/invoice/cancel-or-correct#if-the-cancellation-did-not-reach-taxjar). |

The **Cancelled** label shows on the form. On the TaxJar Transaction Sync page, a cancelled document that TaxJar no longer holds shows as **Synced**, with the transaction status **Cancelled**.
== Exclusion Reasons
| Reason | Meaning | What to do |
|---|---|---|
| TaxJar was switched off for this site when this document was submitted. | **Enable TaxJar** was off. | Turn it on, then [send the invoice](#send-one-invoice-again). |
| Transaction sync was not enabled for this company when this document was submitted. | **Sync Transactions to TaxJar** was off. | Turn it on, then send the invoice. |
| Export transactions sync is disabled. | The company sends domestic sales only, and this is an export. | Nothing, if this is correct. To send exports, select **Domestic + Export** in TaxJar Setup. |
| …submitted before the upgrade from TaxJar version 15. The check of whether TaxJar holds it has not run yet. | A version 15 invoice. | Click **Run the check**. Refer to [Upgrade from Version 15](/setup/upgrade-from-v15). |
| …submitted before the upgrade from TaxJar version 15. TaxJar does not hold it. | The check found that TaxJar does not hold it. | If it must be in TaxJar, click **TaxJar** → **Sync to TaxJar**. |
| This transaction was removed from TaxJar. | Only invoices from older versions of the app show this. | Nothing. |

In the export of the TaxJar Transaction Sync page, a reason that the app found from the current settings has the suffix "(current setting)".
== Customer Sync Statuses
| Status | Meaning |
|---|---|
| **NA** | The customer has no exemption to send. |
| **Queued** | The app sends the customer now. |
| **Synced** | The customer is in TaxJar. |
| **Failed** | TaxJar did not accept the customer. **TaxJar Sync Error** gives the cause. |
| **Not Sent** | The customer waited in the queue for more than 15 minutes. Resync it. |
:::

