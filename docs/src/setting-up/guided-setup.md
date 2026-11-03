---
title: "Guided Setup"
description: "Do the six steps of TaxJar Setup: connect each company, map the ledgers, set the company address, turn on the features and load your nexus states."
type: "how-to"
---

# Guided Setup

We will see how to connect TaxJar to ERPNext through the guided setup experience.

![The TaxJar Setup page in the TaxJar workspace, on the Pre-requisites step, with the six step names, the Setup TaxJar video card, the four checklist items and the Continue button](/images/guided-setup-start.webp)

## Pre-requisites

Before we continue with the setup, we need to get done with the following tasks:

1. TaxJar Account Setup
2. Review Ledger Accounts

---

### TaxJar Account Setup

Before you connect, your TaxJar account needs your nexus states and an API token.

:::tabs
== Sign Up
We need to sign up for a free trial. After 30 days, you need to upgrade to a TaxJar Professional plan to keep using it.

1. Open the [TaxJar sign-up page](https://app.taxjar.com/api_sign_up).

<YouTubeVideo id="2RnyQMNnjME" title="Sign up for TaxJar" :start="27" :end="53" thumbnail="/images/video-setup-signup.webp" />
== API Key
After sign up, let's get our API token to connect to ERPNext.

1. Open the [API Access page](https://app.taxjar.com/account#api-access).
2. Copy the **Live** / **Sandbox** token.

<YouTubeVideo id="2RnyQMNnjME" title="Get the API token from TaxJar" :start="54" :end="65" thumbnail="/images/video-setup-api-token.webp" />
== Manage Nexus
Let's set up state nexus to start collecting taxes for that region.

1. Open the [Nexus Address Configuration page](https://app.taxjar.com/account#api-access:~:text=Nexus%20Address%20Configuration).
2. Click **Add State with Nexus** and add each state where you collect sales tax.

<YouTubeVideo id="2RnyQMNnjME" title="Configure nexus in TaxJar" :start="66" :end="93" thumbnail="/images/video-setup-nexus.webp" />
:::

### Review Ledger Accounts

Let's check that the chart of accounts has the two ledger accounts that the setup needs.

:::tabs
== Sales Tax Ledger
This ledger holds the sales tax that you owe to the state.

1. Open the **Chart of Accounts** of your company.
2. Check for **Sales Tax Payable** (21410) under **Sales Tax Liabilities**. It must be a Liability account. If it is missing, add it as a ledger.

![The Chart of Accounts tree with Sales Tax Payable 21410 under Sales Tax Liabilities](/images/before-coa-sales-tax.webp)
== Shipping Ledger
This ledger holds the shipping and handling fees that you charge to customers.

1. Open the **Chart of Accounts** of your company.
2. Check for **Shipping and Freight Income** (41300) under **Sales Revenue**. It must be an Income or Expense account. If it is missing, add it as a ledger.

![The Chart of Accounts tree with Shipping and Freight Income 41300 under Sales Revenue](/images/before-coa-shipping.webp)
:::

## Continue with Setup

Since the pre-requisites are in place, let's see what are the steps involved in completing the setup.

<YouTubeVideo id="2RnyQMNnjME" title="The six steps of TaxJar Setup" :start="113" thumbnail="/images/video-setup-continue.webp" />

<ol class="steps">
<li><details>
<summary><h3 id="connect">Connect</h3><span>Connect each company to TaxJar with its API token.</span></summary>

![The Connect step with API Mode set to Live, one company with a green Connected status, and the API log settings](/images/setup-step2-connect.webp)

1. In **API Mode**, select **Live** or **Sandbox**.
2. Select the **Company**, and paste its API token.
3. Click **Connect**, and wait for the green **Connected** status.
4. Click **Save & continue**.

To add more companies, click **Add another company**. **Enable API Logs** keeps a log of each call to TaxJar for 15 days.

::: tip If Connect fails
The button changes to **Retry**. Check that the token is for the selected mode. Refer to [Messages & Errors](/troubleshoot/messages-and-errors#setup-messages).
:::

</details></li>
<li><details>
<summary><h3 id="map-ledgers">Map Ledgers</h3><span>Select the sales tax and shipping ledger accounts.</span></summary>

![The Map Ledgers step with Sales Tax Payable and Shipping and Freight Income selected for one company](/images/setup-step3-ledgers.webp)

1. Check **Sales Tax Ledger Account** and **Shipping Ledger Account** for each company.
2. If a field is empty, select an account.
3. Click **Save & continue**.

The app then makes the tax template **TaxJar Sales Tax**, with a shipping row and a sales tax row.

</details></li>
<li><details>
<summary><h3 id="address">Address</h3><span>Select the company address that TaxJar uses as the ship-from address.</span></summary>

![The Address step with the company address and the green Valid badge](/images/setup-step4-address.webp)

1. Select the **Company Address**. If there is none, click **Add address**.
2. Wait for the green **Valid** badge. In Sandbox mode, the badge shows **Skipped**. You can continue.
3. Click **Save & continue**.

**Add address** opens this dialog. Fill in the street, city, state code and postal code.

![The New address dialog with the street, city, state code and postal code filled in, and Preferred Billing Address selected](/images/setup-address-dialog.webp)

</details></li>
<li><details>
<summary><h3 id="features">Features</h3><span>Turn on the tax calculation and the transaction sync.</span></summary>

![The Features step with Compute Taxes on Sales and Sync Transactions to TaxJar selected, and Domestic + Export set](/images/setup-step5-features.webp)

1. Select **Compute Taxes on Sales** to get the tax on quotations, sales orders and invoices.
2. Select **Sync Transactions to TaxJar** to send your invoices to TaxJar for AutoFile.
3. Select **Domestic + Export** to also sync export transactions with TaxJar, or **Domestic only** to sync US sales only.
4. Click **Save & continue**.

</details></li>
<li><details>
<summary><h3 id="sync-nexus">Sync Nexus</h3><span>Load your nexus states from TaxJar, and activate the setup.</span></summary>

![The Sync Nexus step with the blue banner about the daily update and the nexus states of one company](/images/setup-step6-nexus.webp)

1. Wait for **Synced**. Your nexus states show as labels.
2. If a state is missing, click **Manage TaxJar Nexus**, add it in TaxJar, then click the refresh icon.
3. Click **Activate**.

The app updates your nexus states from TaxJar each day.

</details></li>
</ol>

## Summary

The screen shows **TaxJar is configured**, with a summary of the configuration of all companies. To make changes, click **Edit configuration**.

![The TaxJar is configured screen with the Edit configuration button, the Walkthrough video card, the Connection card with Live mode and API logs, and the card of Nova Inc with its 3 nexus regions, ledgers, features and address](/images/setup-summary.webp)
