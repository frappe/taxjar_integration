---
title: "Verify Tax Applicability: check the sales tax on a document"
description: "Read the TaxJar tab and the TaxJar Tax Breakdown of a document to see why TaxJar charged the tax, which address set the rate, and the tax for each jurisdiction."
type: "how-to"
---

# Verify Tax Applicability

Use this when a customer asks about the tax, or when the amount looks wrong.

## Pre-requisites

Save the document. The tax and the breakdown show only after a save.

## Check the tax

::::tabs
== Tax Applicability Matrix
![The TaxJar tab of a Sales Invoice with the Ship From and Ship To addresses and the three cards of the Tax Applicability Matrix](/images/document-tax-matrix.webp)

Open the document, and click the **TaxJar** tab.

**Ship From** and **Ship To** show the two addresses. The address that sets the rate has the label **(Origin based tax)** or **(Destination based tax)**.

| Card | Answers |
|---|---|
| **Do you have a nexus here?** | **Yes** or **No**. With No, there is no tax. |
| **Is the customer taxable?** | **Yes**, **No**, or **Yes, but transaction is marked as exempt**. |
| **Is the product taxable?** | **Yes**, **No** or **Partially**, when only some items are taxable. |
== Jurisdiction Breakdown
![The TaxJar Tax Breakdown section with the tax for the state, county and city, and the total](/images/document-tax-breakdown.webp)

On the **Details** tab, below the totals, open **TaxJar Tax Breakdown**.

The table shows the rate and the tax for the state, the county, the city and each special district. **Are shipping charges taxable?** shows whether the state taxes shipping.
== Missing or Wrong Tax
![The TaxJar Tax Breakdown section of an exempt invoice with the reason that no tax is charged](/images/document-no-tax-reason.webp)

When TaxJar charged no tax, **TaxJar Tax Breakdown** shows the reason in place of the table.

| Reason on the form | Cause |
|---|---|
| Wholesale customer is exempted from taxes, hence no taxes are charged. | The customer has a Wholesale exemption for the ship-to state. Government and Other show the same type of sentence. |
| Wholesale transaction is exempted from taxes, hence no taxes are charged. | The document is marked as exempt with the reason Wholesale. |
| None of the items are taxable in {ship-to}, hence no taxes are charged. | The state does not tax any item on the document. |
| No sales tax applies in {ship-to}, hence no taxes are charged. | TaxJar returned no tax for another reason. |

For other causes, refer to [No Sales Tax on a Document](/help/no-sales-tax).
::::
