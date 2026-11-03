---
title: "Upgrade from Version 15"
description: "What the upgrade from TaxJar version 15 changes, the setup steps after the upgrade, and how to check which older invoices TaxJar already holds."
type: "how-to"
---

# Upgrade from Version 15

Do these steps only if your site used TaxJar with ERPNext version 15. A new site does not need them.

## What Changes

| Data | Version 15 | After the Upgrade |
|---|---|---|
| **Exempt Customer** | **Exempt From Sales Tax** set | Exemption type **Other**, exempt in all US states and Canadian provinces. |
| **Exempt Sale** | **Exempt From Sales Tax** set on a quotation, sales order or sales invoice | **Is transaction exempt from sales tax?** set, with the reason **Other**. |
| **Nexus** | Rows with no company | <Badge type="danger" text="Deleted" /> TaxJar Setup gets the nexus again for each company. |
| **Older Invoices** | Submitted before the upgrade | <Badge type="info" text="Excluded" /> with the reason "Submitted before upgrade, not yet checked". |
| **Print Format** | **US Sales Tax Invoice** | Renamed to **US Sales Tax (Invoice, DN, CN)**. |

::: info
The upgrade does not change a record that already has an exemption of the new version.
:::

## Upgrade Steps

<ol class="steps">
<li><details>
<summary><h3 id="run-taxjar-setup-again">Run TaxJar Setup Again</h3><span>Do the six steps in Live mode, and activate.</span></summary>

1. Open **TaxJar Setup** and do all six steps. Refer to [Guided Setup](/setting-up/guided-setup).
2. On the **Connect** step, set **API Mode** to **Live**.
3. Click **Activate**.

The app then sends each customer exemption that version 15 did not send, and starts the invoice check in the background.

::: tip Check the Exempt Customers
After the upgrade, each exempt customer is exempt in all regions. If a customer is exempt only in some states, change its regions. Refer to [Customer Tax Exemption](/tax-exemptions/customer-tax-exemption).
:::

</details></li>
<li><details>
<summary><h3 id="check-older-invoices">Check Older Invoices</h3><span>Ask TaxJar which invoices from version 15 it holds.</span></summary>

Version 15 sent invoices to TaxJar, but it did not record this on the invoice. The check asks TaxJar which of these invoices it holds, and sets the correct status on each one.

::: tip
Only a TaxJar Manager can run the check. The check runs in Live mode only, so each company needs a Live token.
:::

1. Open **TaxJar API Settings** in the TaxJar sidebar, under **Other**.
2. Click the **Migration** tab. The card **TaxJar Invoice Sync Status** shows the **Upgrade Date** and **Last Checked**.
3. Click **Run check**. The progress shows "Month {n} of {total}". You can leave the page.

To run the check again, click **Run again**.

![The Migration tab of TaxJar Settings on a site that did not upgrade from version 15. The card shows "Nothing to check on this site"](/images/upgrade-migration-tab.webp)

On a site that did not upgrade, the tab shows "Nothing to check on this site", as above.

</details></li>
<li><details>
<summary><h3 id="read-the-results">Read the Results</h3><span>See the result of the check for each company.</span></summary>

The table has one row for each company. The columns **Invoices**, **Found**, **Not Found** and **Stale in TaxJar** count the invoices. "Stale" means that you cancelled the invoice in ERPNext, but TaxJar still holds it.

| Result | Meaning | What to Do |
|---|---|---|
| <Badge type="tip" text="All Found" /> | TaxJar holds all the invoices. | Nothing. |
| <Badge type="danger" text="Needs Review" /> | Some invoices are not in TaxJar, or are stale. | Do [Fix the Results](#fix-the-results). |
| <Badge type="danger" text="Failed" /> | TaxJar did not answer. | Check the Live token in TaxJar Setup, then click **Run again**. |
| <Badge type="warning" text="No Credential" /> | The company has no Live token. | Add a Live token, then run the check. |
| <Badge type="warning" text="Sandbox Mode" /> | The site is in Sandbox mode. | Change to Live, then run the check. |
| <Badge type="info" text="Not Checked" /> | The check did not run for this company. | Click **Run check**. |

**New invoice statuses:**

| Invoice in ERPNext | In TaxJar | New Status |
|---|---|---|
| **Submitted** | Found | <Badge type="tip" text="Synced" /> |
|  | Not found | <Badge type="info" text="Excluded" /> "Not found in TaxJar, submitted before upgrade" |
| **Cancelled** | Still there | <Badge type="danger" text="Failed" /> |

</details></li>
<li><details>
<summary><h3 id="fix-the-results">Fix the Results</h3><span>Send missing invoices, and remove stale ones.</span></summary>

Below the table, an alert shows for each company that needs work.

::::tabs
== Not in TaxJar
1. Click **Show not found**. The TaxJar Transaction Sync page opens with these invoices.
2. Open each invoice that must be in TaxJar.
3. Click **TaxJar** → **Sync to TaxJar**.

::: warning Run the Check First
The **Sync to TaxJar** button does not show on an invoice that waits for the check. This stops the app from sending an invoice that version 15 already sent.
:::
== Stale in TaxJar
1. Click **Show stale**. The TaxJar Transaction Sync page opens on the **Failed** tab.
2. Select the invoices and click **Resync**. The app deletes them from TaxJar.
::::

</details></li>
</ol>
