---
title: "Scheduled Jobs"
description: "The jobs that the TaxJar Integration runs on a schedule: the daily nexus update, the weekly category update, the 15-minute retries and the log cleanup."
type: "reference"
---

# Scheduled Jobs

The app runs these jobs on a schedule. You do not start them.

| How Often | Job | What It Does | Runs When Off |
|---|---|---|:-:|
| **Every 15 Minutes** | Invoice Retry | Sends failed invoices and cancellations again, when the error is temporary. | - |
|  | Customer Retry | Sends failed customers again, when the error is temporary. A customer that waited more than 15 minutes in the queue becomes Failed first. | - |
|  | Customer Removal | Removes customers from the TaxJar account of a company that you took off **Restrict to Companies**. | - |
| **Daily** | Nexus Update | Gets the nexus states of each company from TaxJar. On a failure, it sends a notification to the TaxJar users. Refer to [Daily Update Failure](/setting-up/updating-your-nexus#daily-update-failure). | - |
|  | Log Cleanup | Deletes the TaxJar API Log entries that are older than **Retention**. With 0, it keeps all entries. | ● |
|  | Usage Summary | Sends a summary of the use of the app, only when usage data is on. Refer to [Usage Data & Feedback](/reference/usage-data-and-feedback). | ● |
| **Weekly** | Category Update | Gets the TaxJar product tax categories, and adds only the new ones. | - |

**Runs When Off:** the job also runs when TaxJar is off in **TaxJar Settings**. The other jobs do nothing then.

## Retry Rules

| Rule | Value |
|---|---|
| Tries for each document | Up to 5. After that, send it yourself. Refer to [Resolve Failed Syncs](/transaction-sync/resolve-failed-syncs). |
| Documents in each run | 50 invoices and 50 customers |
| Company with no API token | The failure does not count as a try. The app sends the document after you add the token. |
| Company that no longer syncs | The app does not retry it. |
