---
title: "Upgrade from Version 15"
description: "What the upgrade from TaxJar version 15 changes, the setup steps after the upgrade, and how to check which older invoices TaxJar already holds."
type: "how-to"
---

# Upgrade from Version 15

Do these steps only if your site used TaxJar with ERPNext version 15. A new site does not need them.

## What the upgrade changes

| Version 15 data | After the upgrade |
|---|---|
| A customer with **Exempt From Sales Tax** | Exemption type **Other**, exempt in all US states and Canadian provinces. |
| A quotation, sales order or sales invoice with **Exempt From Sales Tax** | **Is transaction exempt from sales tax?** is set, with the reason **Other**. |
| Nexus rows with no company | Deleted. TaxJar Setup gets the nexus again for each company. |
| Invoices submitted before the upgrade | Status **Excluded**, with the reason "Submitted before upgrade, not yet checked". |
| The print format **US Sales Tax Invoice** | Renamed to **US Sales Tax (Invoice, DN, CN)**. |

The upgrade does not change a record that already has an exemption of the new version.

## Upgrade steps

<ol class="steps">
<li><details>
<summary><h3 id="do-taxjar-setup-again">Do TaxJar Setup again</h3><span>Run the six steps in Live mode, and activate.</span></summary>

1. Open **TaxJar Setup** and do all six steps. Refer to [Guided Setup](/setup/guided-setup).
2. On the **Connect** step, set **API Mode** to **Live**.
3. Click **Activate**.

The app then sends each customer exemption that version 15 did not send, and starts the invoice check in the background.

::: tip Check the exempt customers
After the upgrade, each exempt customer is exempt in all regions. If a customer is exempt only in some states, change its regions. Refer to [Customer Tax Exemption](/sell/exempt-customers).
:::

</details></li>
<li><details>
<summary><h3 id="check-the-invoices-from-before-the-upgrade">Check the invoices from before the upgrade</h3><span>Ask TaxJar which older invoices it holds.</span></summary>

![The Migration tab of TaxJar Settings on a site that did not upgrade from version 15](/images/upgrade-migration-tab.webp)

Version 15 sent invoices to TaxJar, but it did not record this on the invoice. The check asks TaxJar which of these invoices it holds, and sets the correct status on each one.

1. Open **TaxJar API Settings** in the TaxJar sidebar, under **Other**.
2. Click the **Migration** tab. The card **TaxJar Invoice Sync Status** shows the **Upgrade Date** and **Last Checked**.
3. Make sure that **API Mode** is **Live** and that each company has a Live token. The check runs in Live mode only.
4. Click **Run check**. The progress shows "Month {n} of {total}". You can leave the page.

To run the check again, click **Run again**. Only a TaxJar Manager can run the check.

On a site that did not upgrade, the tab shows "Nothing to check on this site".

</details></li>
<li><details>
<summary><h3 id="read-the-results">Read the results</h3><span>See the result of the check for each company.</span></summary>

The table has one row for each company. The columns **Invoices**, **Found**, **Not Found** and **Stale in TaxJar** count the invoices. "Stale" means that you cancelled the invoice in ERPNext, but TaxJar still holds it.

| Result | Meaning | What to do |
|---|---|---|
| **All Found** | TaxJar holds all the invoices. | Nothing. |
| **Needs Review** | Some invoices are not in TaxJar, or are stale. | Do **Fix the results**. |
| **Not Checked** | The check did not run for this company. | Click **Run check**. |
| **Failed** | TaxJar did not answer. | Check the Live token in TaxJar Setup, then click **Run again**. |
| **No Credential** | The company has no Live token. | Add a Live token, then run the check. |
| **Sandbox Mode** | The site is in Sandbox mode. | Change to Live, then run the check. |

The check sets these statuses:

| Invoice | TaxJar | New status |
|---|---|---|
| Submitted | Holds it | **Synced** |
| Submitted | Does not hold it | **Excluded**, reason "Not found in TaxJar, submitted before upgrade" |
| Cancelled | Still holds it | **Failed** |

</details></li>
<li><details>
<summary><h3 id="fix-the-results">Fix the results</h3><span>Send missing invoices, and remove stale ones.</span></summary>

Below the table, an alert shows for each company that needs work.

**Invoices that are not in TaxJar:**

1. Click **Show not found**. The TaxJar Transaction Sync page opens with these invoices.
2. Open each invoice that must be in TaxJar.
3. Click **TaxJar** → **Sync to TaxJar**.

**Cancelled invoices that are still in TaxJar:**

1. Click **Show stale**. The TaxJar Transaction Sync page opens on the **Failed** tab.
2. Select the invoices and click **Resync**. The app deletes them from TaxJar.

::: warning Run the check before you send older invoices
The **Sync to TaxJar** button does not show on an invoice that waits for the check. This stops the app from sending an invoice that version 15 already sent.
:::

</details></li>
</ol>
