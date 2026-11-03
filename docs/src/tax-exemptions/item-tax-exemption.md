---
title: "Item Tax Exemption & Product Categories"
description: "Tell TaxJar how states tax each item with a product tax category, for example food, clothing or software. Set it on the item before you sell."
type: "how-to"
---

# Item Tax Exemption

A product tax category tells TaxJar how each state taxes an item. For example, some states do not tax clothing or food. An item with no category is taxed as general goods.

::: tip
To set the category on items, you need the **Item Manager** role. Refer to [Roles & Permissions](/setting-up/roles-and-permissions).
:::

## Find a Category

Find the category in the [TaxJar product tax codes](https://developers.taxjar.com/api/reference/#categories), or in the app:

1. In the TaxJar sidebar, click **Nexus & Product Category**.
2. In **Product Tax Category**, click **{n} categories configured**.

![The Manage nexus & product category page with the nexus states of one company, Arizona and New York, and 870 product tax categories, each with its sync time and a refresh button](/images/nexus-page.webp)

## Set the Category on an Item

1. Open the **Item**.
2. In **Product Tax Category**, below **Item Group**, select the category.
3. Save the item.

![The Item form with the Product Tax Category list open below Item Group, filtered to clothing categories](/images/item-form-product-tax-category.webp)

::: warning Set the category before you sell
A document keeps the category that the item had when you added it. A later change on the item does not change that document.
:::

## Update the Categories

The app gets new categories from TaxJar each week. To get them now:

1. Open **Nexus & Product Category**.
2. In **Product Tax Category**, click the refresh icon.
3. Wait for the message "Product tax categories fetched and updated."

::: info
Only a TaxJar Manager sees the refresh icon. The app adds new categories, and does not change your own.
:::
