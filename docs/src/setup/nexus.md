---
title: "Update Your Sales Tax Nexus"
description: "Add a nexus state in TaxJar, update the nexus in ERPNext at once, and fix the daily nexus update when the notification says that it failed."
type: "how-to"
---

# Updating your nexus

You collect sales tax only in your nexus states. You keep the list in TaxJar. The app copies it to ERPNext each day.

If a customer is in a state where you have no nexus, the app charges no sales tax.

## Add a nexus state

1. Add the state in [TaxJar → Account → API Access → Nexus Address Configuration](https://app.taxjar.com/account#api-access:~:text=Nexus%20Address%20Configuration).
2. In ERPNext, [update the nexus now](#update-the-nexus-now), or wait for the daily update.

## Update the nexus now

![The State Nexus header with the Synced caption and the refresh icon with its tooltip](/images/nexus-refresh.webp)

You need to be a TaxJar Manager. Refer to [Roles & Permissions](/setup/access).

1. In the TaxJar sidebar, click **Nexus & Product Category**.
2. In **State Nexus**, click the refresh icon.
3. Wait for the message "Nexus regions fetched and updated."
4. Check that the new state is in the company card. If a company has more than six states, click **+{n} more** to see all of them.

## When the daily update fails

If the app cannot get the nexus for a company, it sends a notification to each TaxJar Manager and TaxJar User. The notification shows under the bell icon and names the cause, for example "TaxJar refreshed no nexus for {company}. No usable API credential."

The app keeps the last nexus states that it got. The tax calculation continues with them.

To fix it:

1. Click the notification. **Nexus & Product Category** opens.
2. Fix the cause. For a credential cause, check the token of the company in [TaxJar Setup](/setup/guided-setup#connect).
3. [Update the nexus now](#update-the-nexus-now).

The **Synced** time changes only when all companies update.
