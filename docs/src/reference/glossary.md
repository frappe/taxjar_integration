---
title: "Sales Tax Glossary"
description: "Short definitions of the sales tax and TaxJar terms in these docs, from AutoFile and nexus to exemption, product tax category, sync and Sandbox mode."
type: "reference"
pageClass: "glossary-page"
---

# Glossary

## Sales Tax

| Term | Meaning |
|---|---|
| **Destination-based tax** | The state uses the rate of the ship-to address. |
| **Exemption** | A customer or a sale that pays no sales tax, for example a reseller. Refer to [Customer Tax Exemption](/tax-exemptions/customer-tax-exemption). |
| **Exempt region** | A US state or Canadian province where a customer's exemption applies. |
| **Export** | A sale with a ship-to country that is not the United States. It has no US sales tax. |
| **Jurisdiction** | A level of government that charges sales tax: the state, the county, the city or a special district. |
| **Nexus** | A legal connection to a state. You collect sales tax only in your nexus states. Refer to [Updating your nexus](/setting-up/updating-your-nexus). |
| **Origin-based tax** | The state uses the rate of the ship-from address. |
| **Product tax category** | A TaxJar code that tells TaxJar how states tax an item. Refer to [Item Tax Exemption](/tax-exemptions/item-tax-exemption). |

## Documents & Sync

| Term | Meaning |
|---|---|
| **Credit note** | A sales invoice with **Is Return (Credit Note)** set. TaxJar records it as a refund. Refer to [Credit & Debit Notes](/sales-adjustments/credit-and-debit-notes). |
| **Debit note** | A sales invoice that adds an amount to an earlier invoice. TaxJar records it as an order. |
| **Ship from** | The company address with **Preferred Billing Address** set. |
| **Ship to** | The shipping address of the document. If it is empty, the app asks for one when you save. |
| **Sync** | The app sends a submitted invoice, credit note or customer to TaxJar. Refer to [Syncing to TaxJar](/transaction-sync/syncing-to-taxjar). |
| **TaxJar Sales Tax template** | The tax template that TaxJar Setup makes for each company, with a shipping row and a sales tax row. |
| **Transaction** | An order or a refund in TaxJar, made from an invoice or a credit note. |

## TaxJar Account

| Term | Meaning |
|---|---|
| **API token** | The key from TaxJar that lets the app use one TaxJar account. Each company has a Live token and a Sandbox token. |
| **AutoFile** | A TaxJar service that files your sales tax returns from the transactions in your TaxJar account. |
| **Live mode** | The API mode for real business. TaxJar records the transactions. Refer to [Before you go live](/setting-up/before-you-go-live). |
| **Persona** | A type of TaxJar user: TaxJar Manager or TaxJar User. It is not an ERPNext role. Refer to [Roles & Permissions](/setting-up/roles-and-permissions). |
| **Sandbox mode** | The API mode for tests. TaxJar does not record the transactions. |
