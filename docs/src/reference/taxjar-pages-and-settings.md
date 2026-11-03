---
title: "TaxJar Pages & Settings"
description: "Each TaxJar page in the ERPNext sidebar, the TaxJar fields on ERPNext forms, and the labels in TaxJar Setup and the TaxJar Settings form."
type: "reference"
---

# TaxJar Pages & Settings

## Sidebar Pages

| Section | Link | Use It To |
|---|---|---|
| **Home** | TaxJar Integration | See the setup state and open the other pages. |
| **Setup** | TaxJar Setup | Do the [Guided Setup](/setting-up/guided-setup), and change the setup. |
|  | Customer Tax Exemption | [Exempt many customers](/tax-exemptions/customer-tax-exemption#bulk-exemption), and fix customer syncs. |
|  | Nexus & Product Category | Update the [nexus states](/setting-up/updating-your-nexus) and the [product tax categories](/tax-exemptions/item-tax-exemption). |
| **Reports** | TaxJar Transaction Sync | [Close the period](/tax-return-filing/period-close-and-filing), and [fix failed syncs](/transaction-sync/resolve-failed-syncs). |
| **Other** | TaxJar API Logs | [Read the requests and the answers](/troubleshoot/api-log). |
|  | TaxJar API Settings | Turn TaxJar on or off, and run the [version 15 check](/reference/upgrade-from-version-15). |

::: tip
The **Other** section is closed by default. Click **Other** to open it.
:::

## Fields on ERPNext Forms

| Form | Field or Section | Holds |
|---|---|---|
| **Quotation, Sales Order, Sales Invoice** | **TaxJar** tab | The ship-from and ship-to addresses and the Tax Applicability Matrix. |
|  | **TaxJar Exemptions**, below **Net Total** | The exemption of one sale. |
|  | **TaxJar Tax Breakdown**, below the totals | The tax for each jurisdiction. |
| **Sales Invoice** | **TaxJar Status** in the sidebar | The sync status. |
|  | **Transaction Sync** on the **TaxJar** tab | The sync status. |
| **Customer** | **TaxJar Tax Exemption** on the **Tax** tab | The exemption. |
|  | **TaxJar Sync Details** on the **Tax** tab | The sync status of the customer. |
| **Item** | **Product Tax Category**, below **Item Group** | The TaxJar category of the item. |
| **Address** | **State Code (US)** | The two-letter US state code. |
|  | **Region Code (ISO 3166-2)** | The region code that TaxJar needs. |

The TaxJar fields show only for a company that uses TaxJar.

## Setup & Settings Labels

TaxJar Setup and the TaxJar Settings form use different labels for the same company switches.

| TaxJar Setup | TaxJar Settings |
|---|---|
| **Compute Taxes on Sales** | **Calculate Sales Tax** |
| **Sync Transactions to TaxJar** | **Sync Transactions** |
| **Domestic + Export** | **Include Export Transactions**, set |

::: tip
Change the configuration in [TaxJar Setup](/setting-up/guided-setup), not in the TaxJar Settings form.
:::
