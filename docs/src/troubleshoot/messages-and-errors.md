---
title: "Error Messages & Fixes"
description: "Every message of the TaxJar Integration in one place: setup, saving a document, addresses, sync errors, credit notes, customers, access and the upgrade."
type: "reference"
pageClass: "messages-page"
---

# Messages & Errors

Each section lists the messages of one place in the app, with the cause and the fix.

::: tip
Find a message with the search (Ctrl+K or ⌘K). Text in braces, for example {company}, is a name that changes.
:::

## Setup Messages

These show in TaxJar Setup and on the TaxJar Settings form.

| Message | Cause | Fix |
|---|---|---|
| Invalid token (401). Check you copied the Live token. | The token is wrong, or it is for the other mode. | Copy the token again from TaxJar, for the correct mode. Click **Connect**. |
| Could not reach TaxJar. Check your connection and try again. | The server cannot reach TaxJar. | Check the internet connection of the server, then click **Retry**. |
| Please validate API Key for {company}. | The company is not connected. | Click **Connect** for that company before you continue. |
| Invalid address as per TaxJar. | TaxJar cannot find the company address. | Correct the address, then check it again. |
| At least one Live Token is required in API Credentials for Live mode. | Live mode is on, but no company has a Live token. | Add a Live token. The Sandbox message is the same for Sandbox mode. |

## Save Messages

These show on a quotation, a sales order or a sales invoice.

| Message | Cause | Fix |
|---|---|---|
| Customer address is not set, hence taxes are not calculated. | The document has no address. | Click **Create Address →**, or select an address. |
| Nexus not configured for {state}, hence no taxes are charged. | You have no nexus in the ship-to state. | If you must collect tax there, add the state in TaxJar, then [sync the nexus](/setting-up/updating-your-nexus#on-demand-nexus-sync). |
| Sales taxes are not applicable on export transactions. | The ship-to country is not the United States. | Nothing. |
| Company Address Required: Please set a default address for the company {company}. | The company has no address. | Add a company address in [TaxJar Setup](/setting-up/guided-setup#address). |
| Exchange Rate Not Found: Could not find exchange rate from {currency} to USD for {date}. | The document is not in USD, and ERPNext has no rate. | Add a **Currency Exchange** record to USD, or set up **Currency Exchange Settings**. |
| TaxJar API is unreachable. Tax has not been calculated for this document. | TaxJar did not answer. The document saved without new tax. | Wait, then save again. |
| TaxJar Tax Calculation Failed | TaxJar did not accept the data. | Read the message. If it names an address, correct that address. |
| Address Required: No Shipping Address or Billing Address is set on this transaction. | The document has no address. | Add an address to the customer, and select it on the document. |
| No Addresses Found | The customer has no address. | Add a shipping address to the customer. |
| Destination Required to File | You submit an invoice with no address, for a company that syncs. | Set a **Shipping Address** or a **Billing Address**, then submit. |

## Address Messages

These show when you save an address.

| Message | Fix |
|---|---|
| State Required | Fill in **State/Province**. |
| State Code Required | Fill in **State Code (US)**. |
| Postal Code Required | Fill in **Postal Code**. |
| Company Address Required: {address} is the only address {company} has… | Add another address for the company before you delete or disable this one. |

## Sync Errors

These show as the **Sync Error** of an invoice or a credit note. An error that ends with "Automatic retry is scheduled." is temporary. The app tries again every 15 minutes, up to five times.

| Error | Fix |
|---|---|
| TaxJar API Token is invalid, go to guided setup to configure. | Enter a correct token in [TaxJar Setup](/setting-up/guided-setup#connect), then resync. |
| {company} has no {mode} API token, and TaxJar is in {mode} mode. Enter one in the guided setup. | Enter the token for the current mode. The app then sends the invoice again within 15 minutes. |
| TaxJar is not configured for {company}. Add its API credential in the guided setup. | Connect the company in TaxJar Setup. |
| Transaction ID already exists in TaxJar, please cancel & create a new transaction. | Cancel the invoice, amend it, and submit the new invoice. |
| Exempt transactions cannot have sales tax, please clear exemption or remove sales tax. | Clear the exemption, or remove the sales tax row. |
| Transaction not found in TaxJar, can't update the latest changes. | The transaction is not in TaxJar. Check the [API Log](/troubleshoot/api-log). |
| TaxJar could not process the request: {detail}. | Read the detail. The [API Log](/troubleshoot/api-log) shows the request that TaxJar refused. |
| TaxJar rejected the request as malformed: {detail}. | Read the detail, and correct the field that it names. |
| This TaxJar account is not allowed to make that request | Make sure that your TaxJar plan includes the API. |
| TaxJar's API rate limit was reached | Nothing. The app tries again. |
| TaxJar is unreachable - the request timed out or the connection failed. | Nothing. The app tries again. |
| TaxJar is temporarily unreachable, TaxJar is temporarily offline for maintenance, TaxJar took too long to respond, or TaxJar hit an internal server error | Nothing. The app tries again. |
| TaxJar returned a response that could not be read… | Nothing. It is usually a short outage at TaxJar. The app tries again. |
| No TaxJar payload could be built for this document - check the company's TaxJar configuration. | Check the company in TaxJar Setup. The app tries again. |

### Sync Button Messages

| Message | Fix |
|---|---|
| Invoice Not Submitted | Submit the invoice first. |
| Check Before You Sync | The invoice is from version 15. Run the [upgrade check](/reference/upgrade-from-version-15#check-older-invoices) first. |
| Filing Is Off | Turn on **Sync Transactions to TaxJar** for the company. |
| TaxJar Sync Failed | Read the message below the title. |

## Credit Note Messages

| Message | Fix |
|---|---|
| Original Invoice Not Synced | Send the original invoice to TaxJar, then submit the credit note. |
| TaxJar: Missing Return Reference | Make the credit note from the original invoice: **Create** → **Return / Credit Note**. |
| {customer} has no submitted invoice. | Submit an invoice for the customer, then make the credit note. |
| Please select a Sales Invoice | Select the original invoice in the dialog. |

## Customer Messages

| Message | Fix |
|---|---|
| Nothing to Sync To | No company of this customer uses TaxJar. Check the companies in TaxJar Setup, and **Restrict to Companies** on the customer. |
| Company Not Allowed | The customer does not sync to this company. Check **Restrict to Companies** on the customer. |
| Customer Not Deleted | TaxJar could not remove the customer. Wait, then delete the customer again. |
| Not Sent | The customer waited too long in the queue. Select the row and click **Resync with TaxJar**. |
| Exempt Region Required | Select at least one exempt region, or click **Select All**. |
| …exemption details were saved but not sent to TaxJar. | TaxJar is off, no company uses TaxJar, or the customer is restricted to companies that do not use TaxJar. Fix the cause, then send the customer again. |

## Access Messages

| Message | Fix |
|---|---|
| You do not have {right} access to {document type}, ask your administrator to update permissions for your user. | Ask an administrator to give the role for the task. Refer to [Permissions by Task](/setting-up/roles-and-permissions#permissions-by-task). |
| A TaxJar Manager can fetch them from TaxJar. | Only a TaxJar Manager can update the nexus or the categories. |

## Upgrade Messages

| Message | Fix |
|---|---|
| Live Mode Required | Change **API Mode** to **Live** in TaxJar Setup, then run the check. |
| Nothing to Check | No version 15 invoice waits for the check. Nothing to do. |
| A TaxJar Manager can run the check. | Ask a TaxJar Manager to run the check. |
