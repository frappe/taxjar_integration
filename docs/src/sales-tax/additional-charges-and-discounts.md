---
title: "Shipping, Charges & Discounts"
description: "Enter shipping in the shipping row, see how TaxJar treats other fees and negative rows, and use Additional Discount for a discount on the whole document."
type: "how-to"
---

# Additional Charges & Discounts

TaxJar needs to know which amounts are shipping, which are other charges, and which are discounts. Some states tax shipping, and a discount lowers the taxable amount.

## Charges and discounts

::::tabs
== Shipping
Enter the shipping amount in the **Shipping & Forwarding Charges** row of the taxes table. TaxJar Setup adds this row, on the shipping ledger of the company, to the TaxJar tax template.

![The Sales Taxes and Charges table with the shipping row on the Shipping and Freight Income ledger and the Sales Tax row](/images/shipping-row.webp)

When you save, TaxJar decides if the state taxes the shipping. **TaxJar Tax Breakdown** shows the answer in **Are shipping charges taxable?**.

![The TaxJar Tax Breakdown heading with Are shipping charges taxable? set to No](/images/shipping-taxable.webp)
== Other Charges
![The Confirm Tax Treatment for Extra Charges dialog with one row that increases the taxable value and one row that decreases it](/images/dialog-extra-charges.webp)

When the taxes table has a row on another ledger, the dialog **Confirm Tax Treatment for Extra Charges** opens when you save.

| Row Amount | Type | Sent to TaxJar As |
|---|---|---|
| **Positive**, for example a handling fee | <Badge type="tip" text="Increases Taxable Value" /> | A taxed line named `[OTHER] {ledger name}` |
| **Negative**, for example a rebate | <Badge type="warning" text="Decreases Taxable Value" /> | A discount, spread over the item lines |

Click **Proceed** to save. To change the rows first, click **Cancel**.
== Discounts
- **On the whole document:** use **Additional Discount**, not a negative row in the taxes table. The app sends each item's share to TaxJar as a line discount.
- **On one item:** use the **Discount** of that item row.

![The Additional Discount section with a 10% discount on the Grand Total](/images/additional-discount.webp)

::: info Cash or non-trade discount
ERPNext takes it off after the tax, so TaxJar calculates the tax on the amount before the discount.
:::
::::
