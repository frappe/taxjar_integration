---
title: "TaxJar Pages & Settings"
description: "Each TaxJar page in the ERPNext sidebar, the TaxJar fields on ERPNext forms, and the labels in TaxJar Setup and the TaxJar Settings form."
type: "reference"
---

# TaxJar Pages & Settings

## Pages in the TaxJar sidebar

| Sidebar link | Page | Use it to |
|---|---|---|
| **Home** | TaxJar Integration workspace | See the setup state and open the other pages. |
| **Setup** → **TaxJar Setup** | The guided setup | [Guided Setup](/setup/guided-setup), and change the setup. |
| **Setup** → **Customer Tax Exemption** | TaxJar Customer Configuration | [Exempt many customers](/sell/exempt-customers#exempt-customers), and fix customer syncs. |
| **Setup** → **Nexus & Product Category** | Manage nexus & product category | See and update the [nexus states](/setup/nexus) and the [product tax categories](/setup/product-tax-categories). |
| **Reports** → **TaxJar Transaction Sync** | TaxJar Transaction Sync | [Period Close & Filing](/file/close-a-period), and [fix failed syncs](/file/fix-failed-syncs). |
| **Other** → **TaxJar API Logs** | TaxJar API Log list | [Read the requests and the answers](/help/api-log). |
| **Other** → **TaxJar API Settings** | The TaxJar Settings form | Turn TaxJar on or off, and run the [version 15 check](/setup/upgrade-from-v15). |

The **Other** section is closed by default.

## TaxJar fields on ERPNext forms

| Form | TaxJar part | Holds |
|---|---|---|
| Quotation, Sales Order, Sales Invoice | **TaxJar** tab | The ship-from and ship-to addresses and the Tax Applicability Matrix. |
| Quotation, Sales Order, Sales Invoice | **TaxJar Exemptions**, below **Net Total** | The exemption of one sale. |
| Quotation, Sales Order, Sales Invoice | **TaxJar Tax Breakdown**, below the totals | The tax for each jurisdiction. |
| Sales Invoice | **TaxJar Status** in the sidebar, **Transaction Sync** on the TaxJar tab | The sync status. |
| Customer | **TaxJar Tax Exemption** and **TaxJar Sync Details**, on the **Tax** tab | The exemption and its sync status. |
| Item | **Product Tax Category**, below **Item Group** | The TaxJar category of the item. |
| Address | **State Code (US)** and **Region Code (ISO 3166-2)** | The codes that TaxJar needs. |

The TaxJar parts show only for a company that uses TaxJar.

## Labels in TaxJar Setup and in TaxJar Settings

TaxJar Setup and the TaxJar Settings form use different labels for the same company switches.

| TaxJar Setup | TaxJar Settings |
|---|---|
| **Compute Taxes on Sales** | **Calculate Sales Tax** |
| **Sync Transactions to TaxJar** | **Sync Transactions** |
| **Domestic + Export** | **Include Export Transactions** on |

Use TaxJar Setup to change the configuration.
