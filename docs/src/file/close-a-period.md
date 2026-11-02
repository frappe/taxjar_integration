---
title: "Sales Tax Period Close & Filing"
description: "Before each filing deadline, check on the Transaction Sync page that every invoice of the period is in TaxJar, then review the return in TaxJar."
type: "how-to"
---

# Period Close & Filing

TaxJar AutoFile files your return from the transactions in your TaxJar account. An invoice that is not in TaxJar is not on the return. So before each deadline, you check the period in ERPNext, then in TaxJar.

The app does not file returns, and it does not show the filing status.

## Pre-requisites

- Sync is on for the company, in **Live** mode. Refer to [Before you go live](/setup/go-live).
- You need the TaxJar User roles. Refer to [Roles & Permissions](/setup/access).

## Close the period

<ol class="steps">
<li><details>
<summary><h3 id="check-the-period-in-erpnext">Check the period in ERPNext</h3><span>Make sure that every invoice of the period is in TaxJar.</span></summary>

![The TaxJar Transaction Sync page with the filters, the summary strip, the tabs and the table](/images/sync-page.webp)

**Open the period**

1. In the TaxJar sidebar, click **TaxJar Transaction Sync**.
2. In **Company**, select the company.
3. In **From Date** and **To Date**, enter the first and the last day of the filing period. The dates filter on the **Posting Date**, the same date that TaxJar uses.
4. Keep **Transaction Type** and **Nature** on **All**.

**Read the summary strip**

![The summary strip of the TaxJar Transaction Sync page with one Failed transaction](/images/sync-summary-strip.webp)

| Card | Meaning | What to do |
|---|---|---|
| **Failed** | TaxJar did not accept the transaction. | [Fix it](/file/fix-failed-syncs). |
| **Queued** | The app sends the transaction now. | Wait a few minutes, then check again. |
| **Synced** | The transaction is in TaxJar. | Nothing. |
| **Draft** | The document is not submitted. | Submit it or delete it. |
| **Excluded** | The app did not send the transaction. | Hover over the information icon. Make sure that the reason is correct. |

**The period is ready when**

- [ ] **Failed** is 0.
- [ ] **Queued** is 0.
- [ ] **Draft** is 0, or the drafts are not real sales.
- [ ] Each **Excluded** transaction has a correct reason.
- [ ] In **Transaction Type**, **Credit Note** shows only **Synced** credit notes.

**Keep a record**

1. Click the **All Transactions** tab.
2. Click **Export**.

The Excel file has one row for each transaction, with its status, its error and its last sync time. One export has up to 10,000 rows. For more, use a shorter date range.

</details></li>
<li><details>
<summary><h3 id="file-the-return-in-taxjar">File the return in TaxJar</h3><span>Compare the totals, and let AutoFile file the return.</span></summary>

Do these tasks in your TaxJar account. TaxJar's help article [How does AutoFile work?](https://support.taxjar.com/article/908-how-does-autofile-work) gives the full procedure.

1. Make sure that AutoFile is on for each state where you file.
2. Open the sales tax report for the state and the period.
3. Compare the total sales and the sales tax with ERPNext. Use the ERPNext **Sales Register** report with the same company and dates, and the column of your Sales Tax Ledger Account.
4. If the totals are not the same, go back to [Check the period in ERPNext](#check-the-period-in-erpnext).
5. Let AutoFile file the return before the deadline.

</details></li>
</ol>

## After the return is filed

- Do not cancel or amend the invoices of a filed period. Make a credit note in the current period. Refer to [Cancellations & Amendments](/invoice/cancel-or-correct).
- Do not change the posting date of a synced invoice.
