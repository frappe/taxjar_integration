---
title: "Verify Tax Applicability"
description: "Read the TaxJar tab and the TaxJar Tax Breakdown of a document to see why TaxJar charged the tax, which address set the rate, and the tax for each jurisdiction."
type: "how-to"
---

# Verify Tax Applicability

Each saved quote, order and invoice shows how TaxJar arrived at its sales tax: why tax applies, which address sets the rate, and the tax for each jurisdiction.

::: tip
Save the document first. The tax and the breakdown show only after a save.
:::

::::tabs
== Tax Applicability Matrix
![The TaxJar tab of a Sales Invoice with the Ship From and Ship To addresses and the three cards of the Tax Applicability Matrix](/images/document-tax-matrix.webp)

Open the document, and click the **TaxJar** tab.

**Ship From** and **Ship To** show the two addresses. The address that sets the rate has the label **(Origin based tax)** or **(Destination based tax)**.

| Card | Answer | Meaning |
|---|---|---|
| **Do you have a nexus here?** | <Badge type="tip" text="Yes" /> | You have nexus in the ship-to state. |
|  | <Badge type="danger" text="No" /> | You have no nexus there, so there is no tax. |
| **Is the customer taxable?** | <Badge type="tip" text="Yes" /> | The customer pays sales tax. |
|  | <Badge type="danger" text="No" /> | The customer is exempt. |
|  | <Badge type="warning" text="Yes, but transaction is marked as exempt" /> | The customer pays tax, but this sale is exempt. |
| **Is the product taxable?** | <Badge type="tip" text="Yes" /> | All items are taxable. |
|  | <Badge type="danger" text="No" /> | No item is taxable. |
|  | <Badge type="warning" text="Partially" /> | Only some items are taxable. |

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

For other causes, refer to [Missing Sales Tax](/troubleshoot/missing-sales-tax).
::::
