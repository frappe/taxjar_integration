---
title: "Address Validation: get company and customer addresses ready for tax"
description: "The address fields that TaxJar needs, how the app fills in and checks the US state code, the shipping address dialogs, and the company ship-from address."
type: "how-to"
---

# Address Validation

TaxJar uses two addresses: the company address is the "ship from" address, and the customer address is the "ship to" address. The addresses decide the tax rate. A missing state code or postal code stops the calculation.

For the ship-to address, TaxJar uses the **Shipping Address** of the document. If it is empty, TaxJar uses the **Billing Address**.

## Fill in a US address

Fill in these fields:

- **Address Line 1**
- **City/Town**
- **State/Province**
- **State Code (US)**: the app fills it in when you type the state.
- **Postal Code**
- **Country**

![The Address form with State/Province, State Code (US), Country and Postal Code filled in](/images/address-state-code.webp)

A sentence under the code tells you the result:

| Sentence | Meaning |
|---|---|
| "Auto-filled based on State/Province." | The app found the code from the state. |
| "Cannot find state code, please select from dropdown." | The state is not a US state name. Select the code in **State Code (US)**. |
| "Cannot find region code, using fallback code." | For an address outside the US, the app found no region. It sets **Region Code (ISO 3166-2)** to **XX**. TaxJar accepts this code. |

You can change a code that the app filled in. The app keeps your code when you change the state.

## Add an address from a dialog

The **New Address** dialog and the **New Customer** quick entry also show **State Code (US)** and **Region Code (ISO 3166-2)** below **State**. They fill in **Country** with the country of **System Settings**.

In the **New Customer** and **New Supplier** quick entries, the address is optional. When you type **Address Line 1** or **City**, both fields become necessary. For a US address, **State Code (US)** is then necessary too.

![The New Customer dialog with a US address and State Code (US) filled in from the state](/images/quick-entry-address-codes.webp)

## Dialogs when you save a document

| Dialog | Opens when | What to do |
|---|---|---|
| **Select Shipping Address** | The document has no shipping address, and the customer has addresses. | Select an address and click **Use Selected**. Select **Use this address as shipping address for future transactions** to keep it. If the address is not in the list, click **Add New Address**. |
| **Complete the Shipping Address** | The ship-to address has no street, city, state, postal code or country. | Fill in the empty fields and click **Continue**. The app saves the address, then the document. |
| **No Addresses Found** | The customer has no address. Quotations do not show it. | Add a shipping address to the customer, then save again. |

## The company address

Set it in [the Address step of TaxJar Setup](/setup/guided-setup#address). Select an address for each company, or click **Add address**, and wait for the green **Valid** badge.

When you save the step, the app sets **Preferred Billing Address** on the selected address, and clears it on the other addresses of the company. The tax calculation uses the address with this setting.

You cannot delete or disable the only address of a TaxJar company. Add another address first.
