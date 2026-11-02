---
title: "Customer Tax Exemption: exempt customers from sales tax, one or many"
description: "Set a Wholesale, Government or Other exemption on one customer or on many customers, choose the exempt states, and check that TaxJar received it."
type: "how-to"
---

# Customer Tax Exemption

Set an exemption on customers who do not pay sales tax, for example resellers and government agencies. TaxJar then charges no tax to that customer in the exempt states.

## Pre-requisites

- You need **Sales User** in addition to your TaxJar roles. Refer to [Roles & Permissions](/setup/access).
- Get the exemption certificate from the customer, and keep it. TaxJar and the app do not store certificates.

## Choose the exemption type

| Exemption type | Use it for |
|---|---|
| **Wholesale** | Buyers who resell the goods. |
| **Government** | Government agencies. |
| **Other** | Other exempt buyers, for example non-profit organizations. |
| **Non Exempt** | Customers who pay tax in all states. |

Wholesale, Government and Other need **exempt regions**: the US states and Canadian provinces where the exemption applies. The exemption applies only when the ship-to address is in one of these regions. To exempt a customer everywhere, click **Select All**.

## Exempt customers

::::tabs
== One Customer
![The Manage Exemption dialog with the type Wholesale and two US states selected](/images/customer-manage-exemption-dialog.webp)

1. Open the **Customer**, and go to the **Tax** tab.
2. In **TaxJar Tax Exemption**, click **Manage Exemption**.
3. Select the **Exemption Type**, and the regions in **US States** and **CA Provinces**.
4. Click **Apply**.

The section then shows the type and the exempt regions, and the app sends the exemption to TaxJar. **TaxJar Sync Status** on the customer shows **Synced**.
== Many Customers
![The TaxJar Customer Configuration page with the summary strip, the tabs, two selected rows and the Bulk Action menu open](/images/customers-page.webp)

1. In the TaxJar sidebar, click **Customer Tax Exemption**.
2. Select the customers. Use the tabs or the filters to find them.
3. Click **Bulk Action** → **Configure Exemption…**.
4. Select the **Exemption Type** and the regions, and click **Apply**.

::: warning Apply replaces the regions
**Apply** replaces the exempt regions of every selected customer.
:::

To remove exemptions, use **Bulk Action** → **Clear Exemption**. To get the list as an Excel file, click **Export**.
::::

If a customer shows **Failed**, refer to [Resolve Failed Syncs](/file/fix-failed-syncs#resolve-a-failed-sync), in the **Customers** tab.

## Customers of more than one company

The app sends the customer to the TaxJar account of each TaxJar company. If **Restrict to Companies** is set on the customer, the app sends it only to those companies. When you remove a company from that list, the app removes the customer from the TaxJar account of that company.

To send one customer to one company again, open the customer and click **TaxJar** → **Sync to TaxJar**. If the customer belongs to more than one company, select the **Company** in the dialog and click **Sync**.
