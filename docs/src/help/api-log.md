---
title: "TaxJar API Log"
description: "Find the TaxJar API Log entries of one document or one company, read the request and the response, and set how many days the app keeps the logs."
type: "how-to"
---

# API Log

The TaxJar API Log records each request that the app sends to TaxJar, and each answer. Use it when an error message is not enough.

## Pre-requisites

- **Enable API Logs** must be on in [TaxJar Setup](/setup/guided-setup#connect).
- You need read on TaxJar API Log, for example the **Accounts User** role.

## Find the entries of a document

1. In the TaxJar sidebar, open **Other** → **TaxJar API Logs**.
2. Filter by **Reference Name** to find one document, or by **Company** to find one company.
3. Open the entry with the status **error**.
4. Read **Error** and **Response**.

![The TaxJar API Log list with the Action, Status, Reference DocType and Reference Name columns](/images/api-log-list.webp)

| Status | Meaning |
|---|---|
| **request** | The app sent a request. |
| **success** | TaxJar accepted the request. |
| **error** | TaxJar did not accept the request, or the app could not reach TaxJar. |
| **skipped** | The app did not send the request. **Error** gives the reason. |
| **reused** | The app kept the sales tax that was already on the document, and did not send a request. Refer to [Tax Computation](/sell/how-tax-is-calculated#when-the-app-keeps-the-tax). |

The app writes error entries in the background. A new error entry can take up to 15 minutes to show.

## Change how long the app keeps logs

The app deletes logs after the number of days in **Retention**. The default is 15 days. 0 keeps all logs.

1. Open **TaxJar Setup**, and click **Edit configuration**.
2. On the **Connect** step, change **Retention**.
3. Click **Save & continue**.
