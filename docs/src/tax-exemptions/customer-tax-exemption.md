---
title: "Customer Tax Exemption"
description: "Set a Wholesale, Government or Other exemption on one customer or on many customers, choose the exempt states, and check that TaxJar received it."
type: "how-to"
---

# Customer Tax Exemption

Set an exemption on customers who do not pay sales tax, for example resellers and government agencies. TaxJar then charges no tax to that customer in the exempt states.

## Pre-requisites

- You need **Sales User** in addition to your TaxJar roles. Refer to [Roles & Permissions](/setting-up/roles-and-permissions).
- Get the exemption certificate from the customer, and keep it. TaxJar and the app do not store certificates.

## Exemption Types

| Exemption type | Use it for |
|---|---|
| **Wholesale** | Buyers who resell the goods. |
| **Government** | Government agencies. |
| **Other** | Other exempt buyers, for example non-profit organizations. |
| **Non Exempt** | Customers who pay tax in all states. |

Wholesale, Government and Other need **exempt regions**: the US states and Canadian provinces where the exemption applies. The exemption applies only when the ship-to address is in one of these regions. To exempt a customer everywhere, click **Select All**.

## Single Exemption

::::tabs
== Open the Customer
Open the **Customer**, and go to the **Tax** tab. The **TaxJar Tax Exemption** section shows the current exemption.

![The Tax tab of a customer with the TaxJar Tax Exemption section, Non-Exempted, and the edit icon](/images/customer-tax-tab.webp)
== Set the Exemption
1. In **TaxJar Tax Exemption**, click the edit icon (**Manage Exemption**).
2. Select the **Exemption Type**, and the regions in **US States** and **CA Provinces**.
3. Click **Apply**.

![The Manage Exemption dialog with the type Wholesale, Arizona and California selected, and the CA Provinces list](/images/customer-manage-exemption-full.webp)
== Exemption Applied
The section shows the type and the exempt regions, and the app sends the exemption to TaxJar. **TaxJar Sync Details** shows **TaxJar Sync Status** as **Synced**.

![The Tax tab of an exempt customer with Exempted Wholesale, two US states, two Canadian provinces, and TaxJar Sync Status Synced](/images/customer-exemption-applied.webp)
::::

## Bulk Exemption

::::tabs
== Set the Exemption
1. In the TaxJar sidebar, click **Customer Tax Exemption**.
2. Select the customers. Use the tabs or the filters to find them.
3. Click **Bulk Action** → **Configure Exemption…**.
4. Select the **Exemption Type** and the regions, and click **Apply**.

::: warning Apply replaces the regions
**Apply** replaces the exempt regions of every selected customer.
:::

![The TaxJar Customer Configuration page with the summary strip, the tabs, two selected rows and the Bulk Action menu open](/images/customers-page.webp)
== Clear the Exemption
Select the customers, and click **Bulk Action** → **Clear Exemption**. The app removes the exemption type and the exempt regions of each customer, and sends the change to TaxJar.

![The TaxJar Customer Configuration page with two customers selected and the Bulk Action menu open on Clear Exemption](/images/customers-clear-exemption.webp)
== Export the List
Click **Export** to get the customer list as an Excel file.

![The TaxJar Customer Configuration page with the Export button next to Bulk Action](/images/customers-export.webp)
::::

If a customer shows **Failed**, refer to [Resolve Failed Syncs](/transaction-sync/resolve-failed-syncs#resolve-a-failed-sync), in the **Customers** tab.

## Multi-Company Customers

The app sends the customer to the TaxJar account of each TaxJar company, unless **Restrict to Companies** is set on the customer.

| Restrict to Companies | The app sends the customer to |
|---|---|
| **Empty** | Every TaxJar company |
| **Set** | Only the companies in the list |

::: info Removing a company
When you remove a company from **Restrict to Companies**, the app removes the customer from the TaxJar account of that company.
:::

To send one customer to one company again:

1. Open the customer, and click **TaxJar** → **Sync to TaxJar**.
2. If the customer belongs to more than one company, select the **Company** in the dialog, and click **Sync**.
