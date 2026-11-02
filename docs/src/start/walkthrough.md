---
title: "Walkthrough of the TaxJar Integration in ERPNext"
description: "A video of all TaxJar features in ERPNext, and a tour of the TaxJar workspace: setup, transactions, exemptions, and tax returns and liability."
type: "tutorial"
---

# Walkthrough

## Sales Tax Lifecycle

This video shows all the features that we support as a part of the integration.

<YouTubeVideo id="Y-ppuE5RsLg" title="TaxJar in ERPNext: a walkthrough of all features" />

## TaxJar Workspace

A dedicated space to manage all your sales tax operations.

![The TaxJar workspace in ERPNext, with the TaxJar sidebar, the banner "Configure TaxJar Integration" with the link to the guided setup, and the Manage, Report and Other cards](/images/taxjar-workspace.webp)

We will first go through the guided setup, nexus states and product tax categories. Then we will see how to manage transactions and tax exemptions. {.section-intro}

### Setting Up

:::tabs
== Guided Setup
Connect each company to TaxJar by adding the API credentials, mapping the ledgers, setting the company address, choosing the features, and syncing your nexus.

![The Connect step with API Mode set to Live, one company with a green Connected status, and the API log settings](/images/setup-step2-connect.webp)

For each step in detail, refer to [Guided Setup](/setup/guided-setup#continue-with-setup).
== Nexus & Product Category
Review & fetch your state nexus & product tax category list.

![The Manage nexus & product category page with the nexus states of one company, Arizona and New York, and 870 product tax categories, each with its sync time and a refresh button](/images/nexus-page.webp)
:::

### Manage Transactions

:::tabs
== Sales Tax
When you save a quotation, sales order, sales invoice, credit note or debit note, ERPNext gets the sales tax from TaxJar and adds it to the taxes table.

![A submitted Sales Invoice with the status Unpaid, and the shipping row and the sales tax row in the Sales Taxes and Charges table](/images/invoice-sales-tax.webp)
== Jurisdiction based tax
See the tax for each jurisdiction: state, county, city and special district.

![The TaxJar Tax Breakdown of a Sales Invoice with the rate and the tax for the state, Cook County, the city of Chicago and a special district, and a total of 10.5%](/images/invoice-tax-breakdown.webp)
== Tax Applicability Matrix
Analyze the transaction for origin or destination based tax, and assess the tax applicability based on parameters.

![The TaxJar tab of a submitted Sales Invoice with Ship From Los Angeles, Ship To Chicago with destination based tax, and the three Yes cards of the Tax Applicability Matrix](/images/invoice-tax-matrix.webp)
== Sync Report
Reconcile & check the sync status of submitted invoices, credit notes and debit notes before you file your tax returns.

![The TaxJar Transaction Sync page for the company Nova Tech, with the counts of failed, queued, synced, draft and excluded transactions, and a table of sales invoices, credit notes and debit notes with their sync status](/images/sync-report.webp)
:::

### Manage Tax Exemptions

:::tabs
== Customer Exemption
Classify customers as exempted in specific regions based on their type: Wholesale, Government, Other.

![The TaxJar Customer Configuration page with the counts of total, exempted, non-exempted and not configured customers, and a table of eight customers with their exemption type, exempted regions and sync status](/images/customer-exemption-bulk.webp)
== Product Exemption
Set a **Product Tax Category** on an item so that TaxJar can assess the tax applicability based on the state.

![A new item, Sparkling Mineral Water, with the Product Tax Category Bottled Water, code 40060, selected from the list](/images/item-product-exemption.webp)
:::

### Tax Returns & Liability

:::tabs
== State-wise Tax Liability
Know your tax liability across all the states.

![The TaxJar sales tax insights dashboard with Arizona and New York, the next filing due date, the filing frequency, the actual sales tax collected and the buttons Sales Tax Report and Enroll in AutoFile for each state](/images/taxjar-insights-dashboard.webp)
== Sales Tax Report
See your sales tax liability for each state and filing period, and file your returns with AutoFile.

![The TaxJar sales tax report for New York for one quarter, with the gross sales, the tax collected for each jurisdiction, the minimum sales tax due and the button Enroll in AutoFile](/images/intro-state-return.webp)
:::
