---
title: "Item Tax Exemption & Product Categories"
description: "Tell TaxJar how states tax each item with a product tax category, for example food, clothing or software. Set it on the item before you sell."
type: "how-to"
---

# Item Tax Exemption

A product tax category tells TaxJar how each state taxes an item. For example, some states do not tax clothing or food. An item with no category is taxed as general goods.

## Pre-requisites

- You need the **Item Manager** role. Refer to [Roles & Permissions](/setup/access).
- Find the category in the [TaxJar product tax codes](https://developers.taxjar.com/api/reference/#categories), or in the **All Categories** tab below.

## Product tax categories

::::tabs
== Set on an Item
![The New Item dialog with the Product Tax Category list open below Item Group](/images/item-product-tax-category.webp)

1. Open the **Item**.
2. In **Product Tax Category**, below **Item Group**, select the category.
3. Save the item.

::: warning Set the category before you sell
A document keeps the category that the item had when you added it. A later change on the item does not change that document.
:::
== All Categories
![The Manage nexus & product category page with the nexus states of one company, Arizona and New York, and 870 product tax categories, each with its sync time and a refresh button](/images/nexus-page.webp)

1. In the TaxJar sidebar, click **Nexus & Product Category**.
2. In **Product Tax Category**, click **{n} categories configured**.
== Get New Categories
The app gets new categories from TaxJar each week. To get them now:

1. Open **Nexus & Product Category**.
2. In **Product Tax Category**, click the refresh icon.
3. Wait for "Product tax categories fetched and updated."

Only a TaxJar Manager sees the refresh icon. The app adds new categories, and does not change your own.
::::
