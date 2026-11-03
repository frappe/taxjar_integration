---
title: "Switch from Sandbox to Live Mode"
description: "Sandbox mode is for tests and TaxJar does not record its transactions. Change to Live mode, connect each company with its Live token, and check the result."
type: "how-to"
---

# Before you go live

The app has two API modes. Use Sandbox mode to test the setup, and Live mode to run your business.

| | Sandbox Mode | Live Mode |
|---|:-:|:-:|
| Current tax rates | | ● |
| TaxJar records the transactions for reports and AutoFile | | ● |
| API calls are free of your TaxJar plan quota | ● | |

The mode applies to all companies on the site. Each company has one Sandbox token and one Live token.

## Pre-requisites

- Copy the **Live** API token of each company from [TaxJar → Account → API Access](https://app.taxjar.com/account#api-access).
- You need to be a TaxJar Manager. Refer to [Roles & Permissions](/setting-up/roles-and-permissions).

::: warning Change the mode before you submit real invoices
An invoice that you submit in Sandbox mode goes to the TaxJar sandbox. It shows **Synced**, but it is not in your Live TaxJar account, and AutoFile does not file it.
:::

## Go Live

<ol class="steps">
<li><details>
<summary><h3 id="change-the-mode">Change the mode</h3><span>Switch to Live, and connect each company with its Live token.</span></summary>

1. Open **TaxJar Setup** and click **Edit configuration**.
2. On the **Connect** step, in **API Mode**, click **Live**.
3. For each company, paste the Live token into **Live token**, then click **Connect**. Wait for the green **Connected** status.
4. Click **Save & continue** on each step, then click **Activate**.

::: info What the app does after you save
- It gets the nexus states again for each company.
- In Live mode, it sends to TaxJar each exempt customer that is not in TaxJar yet.
- If the site upgraded from TaxJar version 15, it starts the check of the older invoices. Refer to [Upgrade from Version 15](/reference/upgrade-from-version-15).
:::

</details></li>
<li><details>
<summary><h3 id="check-the-result">Check the result</h3><span>Make sure that the setup is in Live mode, and test one invoice.</span></summary>

1. Open **TaxJar Setup**. The **Connection** card shows **API Mode** as **Live**.
2. Save a test sales invoice for a customer in a nexus state. Check that it has a **Sales Tax** row. Then delete the invoice.

</details></li>
</ol>

## Missing Live Token

A company that has no token for the current mode gets no tax, and its invoices do not sync. The sync error is:

> {company} has no Live API token, and TaxJar is in Live mode. Enter one in the guided setup.

1. Add the Live token of the company on the **Connect** step of TaxJar Setup.
2. The app sends the failed invoices again within 15 minutes. To send them at once, refer to [Resolve Failed Syncs](/transaction-sync/resolve-failed-syncs).

## Turn Off the App

To stop TaxJar for all companies:

1. Open **TaxJar API Settings**.
2. Clear **Enable TaxJar**, and save.

Then:

- The app calculates no tax and sends no transactions.
- It hides its parts on the forms.
- Invoices that you submit get the status **Excluded**.
- The TaxJar Sales Tax template is no longer the default template.
- The standard templates "US ST 6%", "US ST 4%" and "US ST 6.25%" stay disabled.
