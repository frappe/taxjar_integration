---
title: "Scheduled Jobs"
description: "The jobs that the TaxJar Integration runs on a schedule: the daily nexus update, the weekly category update, the 15-minute retries and the log cleanup."
type: "reference"
---

# Scheduled Jobs

The app runs these jobs on a schedule. You do not start them.

| How often | Job | What it does |
|---|---|---|
| Daily | Nexus update | Gets the nexus states of each company from TaxJar. On a failure, it sends a notification to the TaxJar users. Refer to [Updating your nexus](/setup/nexus#when-the-daily-update-fails). |
| Daily | Log cleanup | Deletes the TaxJar API Log entries that are older than **Retention**. With 0, it keeps all entries. |
| Daily | Usage summary | Sends a summary of the use of the app, only when usage data is on. Refer to [Usage Data & Feedback](/reference/usage-data). |
| Weekly | Category update | Gets the TaxJar product tax categories, and adds only the new ones. |
| Every 15 minutes | Invoice retry | Sends failed invoices and cancellations again, when the error is temporary. |
| Every 15 minutes | Customer retry | Sends failed customers again, when the error is temporary. A customer that waited more than 15 minutes in the queue becomes Failed first. |
| Every 15 minutes | Customer removal | Removes customers from the TaxJar account of a company that you took off **Restrict to Companies**. |

## Retry rules

- The app tries a document again up to five times. After that, send it yourself. Refer to [Resolve Failed Syncs](/file/fix-failed-syncs).
- Each run handles up to 50 invoices and up to 50 customers.
- A failure because a company has no API token does not count as one of the five tries. The app sends the document after you add the token.
- The app does not retry a company that no longer syncs.

All jobs, except the log cleanup and the usage summary, do nothing when TaxJar is off.
