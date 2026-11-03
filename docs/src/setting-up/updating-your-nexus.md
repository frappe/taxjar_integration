---
title: "Update Your Sales Tax Nexus"
description: "Add a nexus state in TaxJar, update the nexus in ERPNext at once, and fix the daily nexus update when the notification says that it failed."
type: "how-to"
---

# Updating your nexus

You collect sales tax only in the states where you have nexus, so a customer in any other state pays no sales tax. You manage your nexus states in TaxJar, and the app copies them to ERPNext every day.

## Add Nexus State

1. In TaxJar, go to **Account → API Access → Nexus Address Configuration**, and add the state. [Open the page in TaxJar](https://app.taxjar.com/account#api-access:~:text=Nexus%20Address%20Configuration)
2. In ERPNext, [sync the nexus](#on-demand-nexus-sync) to get the new state at once. If you do not, the daily update adds it.

## On-Demand Nexus Sync

![The State Nexus section with the Synced caption, the refresh icon with the tooltip "Fetch nexus regions from TaxJar", and the nexus states of one company](/images/nexus-sync-tooltip.webp)

You need to be a TaxJar Manager. Refer to [Roles & Permissions](/setting-up/roles-and-permissions).

1. In the TaxJar sidebar, click **Nexus & Product Category**.
2. In **State Nexus**, click the refresh icon.
3. Wait for the message "Nexus regions fetched and updated."
4. Check that the new state is in the company card. If a company has more than six states, click **+{n} more** to see all of them.

## Daily Update Failure

If the daily update cannot get the nexus for a company, each TaxJar Manager and TaxJar User gets a notification under the bell icon. The notification names the cause, for example:

> TaxJar refreshed no nexus for {company}. No usable API credential.

Until you fix the cause, the app uses the last nexus states that it got, so the tax calculation continues.

1. Click the notification. **Nexus & Product Category** opens.
2. Fix the cause. For a credential cause, check the token of the company in [TaxJar Setup](/setting-up/guided-setup#connect).
3. [Sync the nexus](#on-demand-nexus-sync). The **Synced** time changes only when the sync succeeds for all companies.
