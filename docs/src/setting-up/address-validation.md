---
title: "Address Validation"
description: "The address fields that TaxJar needs, how the app fills in and checks the US state code, the shipping address dialogs, and the company ship-from address."
type: "how-to"
---

# Address Validation

TaxJar uses two addresses to find the tax rate: the company address is the "ship from" address, and the customer address is the "ship to" address. A missing state code or postal code stops the calculation.

For the ship-to address, TaxJar uses the **Shipping Address** of the document. If it is empty when you save, the app asks you to select one of the customer's addresses, or to add a new one. A document with a **Billing Address** in another country needs no Shipping Address.

## Address Fields

The fields that an address needs vary based on the country.

:::tabs
== United States
| Field | Required | Note |
|---|:-:|---|
| **Address Line 1** | ● | |
| **City/Town** | ● | |
| **State/Province** | ● | The full state name, for example California. |
| **State Code (US)** | ● | The app fills it in from the state. When you select a code, the app fills in the state. |
| **Postal Code** | ● | |
| **Country** | ● | |

![The Address form with State/Province, State Code (US), Country and Postal Code filled in](/images/address-state-code.webp)
== Canada
| Field | Required | Note |
|---|:-:|---|
| **Address Line 1** | ● | |
| **City/Town** | ● | |
| **State/Province** | ● | The province, for example Ontario. |
| **Region Code (ISO 3166-2)** | Auto | The app fills it in from the province, for example `ON`. |
| **Country** | ● | |
== Other Countries
| Field | Required | Note |
|---|:-:|---|
| **Address Line 1** | ● | |
| **City/Town** | ● | |
| **State/Province** | | Fill it in, so that the app can find the region code. |
| **Region Code (ISO 3166-2)** | Auto | The app fills it in from the state. If no region matches, the app uses `XX`, which TaxJar accepts. |
| **Country** | ● | |

TaxJar charges no US sales tax on a sale to another country.
:::

## Autofill for State & Region Code

A message under **State Code (US)** or **Region Code (ISO 3166-2)** tells you the result.

::: tip Auto-filled based on State/Province.
The app found the code from the state. You do not need to do anything.
:::

::: warning Cannot find state code, please select from dropdown.
For a US address, the state is not a US state name. Select the code in **State Code (US)**.
:::

::: info Cannot find region code, using fallback code.
For an address outside the US, no region matches the state. The app uses `XX`, which TaxJar accepts. To send the correct region, correct the state or type the code.
:::

For an address outside the US, you can type a different region code. The app keeps your code when you change the state. For a US address, **State Code (US)** always changes with the state.

## Address in a Quick Entry

The **New Address** dialog and the **New Customer** quick entry work like the Address form:

- The country defaults to the one set in **System Settings**.
- As you type the state, the app fills in its state code or region code, just below State/Province.
- The address is optional in **New Customer** and **New Supplier**. Once you start typing Address Line 1 or City, both fields become required, along with the state code for a US address.

![The Primary Address Details of the New Customer quick entry with a US address, and State Code (US) filled in from the state](/images/quick-entry-us-address.webp)

## Shipping Address Selection

:::tabs
== Select Shipping Address
**Opens when** the document has no shipping address, and the customer has addresses.

1. Select an address, and click **Use Selected**.
2. To use the address on later documents too, select **Use this address as shipping address for future transactions**.

If the address is not in the list, click **Add New Address**.

![The Select Shipping Address dialog with two customer addresses, the option to use the address on future transactions, and the Use Selected button](/images/dialog-select-shipping.webp)
== Complete the Shipping Address
**Opens when** the ship-to address has no street, city, state, postal code or country.

Fill in the empty fields, and click **Continue**. The app saves the address, then the document.

![The Complete the Shipping Address dialog with the empty Postal Code field outlined in red](/images/dialog-complete-shipping.webp)
== No Addresses Found
**Opens when** the customer has no address. A quotation saves without it.

Click **Add New Address**, and add a shipping address to the customer. The app then saves the document again.

![The No Addresses Found message with the Add New Address button](/images/dialog-no-addresses.webp)
:::

## Company Address

Set it in [the Address step of TaxJar Setup](/setting-up/guided-setup#address). Select an address for each company, or click **Add address**, and wait for the green **Valid** badge.

When you save the step, the app sets **Preferred Billing Address** on the selected address, and clears it on the other addresses of the company. The tax calculation uses the address with this setting.

::: tip
You cannot delete or disable the only address of a TaxJar company. Add another address first.
:::
