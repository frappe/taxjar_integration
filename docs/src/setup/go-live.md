---
title: "Before you go live: change from Sandbox mode to Live mode"
description: "Sandbox mode is for tests and TaxJar does not record its transactions. Change to Live mode, connect each company with its Live token, and check the result."
type: "how-to"
---

# Before you go live

The app has two API modes. Only Live mode puts your invoices in your TaxJar account for reports and AutoFile.

| | Sandbox mode | Live mode |
|---|---|---|
| Use it to | Test the setup. | Run your business. |
| Tax rates | Can be old. | Current. |
| Transactions | TaxJar does not record them. | TaxJar records them for reports and AutoFile. |
| Plan quota | Calls do not use your quota. | Calls use your quota. |
| API token | The Sandbox token of each company | The Live token of each company |

The mode applies to all companies on the site. Each company has one Live token and one Sandbox token.

## Pre-requisites

- Copy the **Live** API token of each company from [TaxJar → Account → API Access](https://app.taxjar.com/account#api-access).
- You need to be a TaxJar Manager. Refer to [Roles & Permissions](/setup/access).

::: warning Change the mode before you submit real invoices
An invoice that you submit in Sandbox mode goes to the TaxJar sandbox. It shows **Synced**, but it is not in your Live TaxJar account, and AutoFile does not file it.
:::

## Go live

<ol class="steps">
<li><details>
<summary><h3 id="change-the-mode">Change the mode</h3><span>Switch to Live, and connect each company with its Live token.</span></summary>

1. Open **TaxJar Setup** and click **Edit configuration**.
2. On the **Connect** step, in **API Mode**, click **Live**.
3. For each company, paste the Live token into **Live token**, then click **Connect**. Wait for the green **Connected** status.
4. Click **Save & continue** on each step, then click **Activate**.

When you save a new mode in TaxJar Setup, the app gets the nexus states again for each company.

When the mode changes to Live, the app also does these tasks in the background:

- It sends to TaxJar each exempt customer that is not in TaxJar yet.
- If the site upgraded from TaxJar version 15, it starts the check of the older invoices. Refer to [Upgrade from Version 15](/setup/upgrade-from-v15).

</details></li>
<li><details>
<summary><h3 id="check-the-result">Check the result</h3><span>Make sure that the setup is in Live mode, and test one invoice.</span></summary>

1. Open **TaxJar Setup**. The **Connection** card shows **API Mode** as **Live**.
2. Save a test sales invoice for a customer in a nexus state. Check that it has a **Sales Tax** row. Then delete the invoice.

</details></li>
</ol>

## If a company has no Live token

A company that has no token for the current mode gets no tax, and its invoices do not sync. The sync error is "{company} has no Live API token, and TaxJar is in Live mode. Enter one in the guided setup." Add the token on the **Connect** step. The app then sends the failed invoices again within 15 minutes. To send them at once, refer to [Resolve Failed Syncs](/file/fix-failed-syncs).

## Turn off the app

There are two ways to stop TaxJar for all companies.

### Clear Enable TaxJar

1. Open **TaxJar API Settings**.
2. Clear **Enable TaxJar**, and save.

The app then calculates no tax, sends no transactions, and hides its parts on the forms. Invoices that you submit get the status **Excluded**. The TaxJar Sales Tax template is no longer the default template. The standard templates "US ST 6%", "US ST 4%" and "US ST 6.25%" stay disabled.

### Disable the app

When you disable the TaxJar Integration app on the site:

- The app hides its fields. It does not delete your data.
- The TaxJar Sales Tax template is no longer the default template.
- The app enables "US ST 6%", "US ST 4%" and "US ST 6.25%" again.
- The scheduled jobs stop.

::: warning Select a default tax template
After you disable the app, no sales tax template is the default. Select a default **Sales Taxes and Charges Template** for each company.
:::

When you enable the app again, the fields and the default template come back.
