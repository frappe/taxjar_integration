---
title: "Usage Data & Feedback: the usage data that the app sends, and the feedback card"
description: "The usage data that the TaxJar Integration sends to Frappe, the data that it never sends, how to turn usage data off, and when the feedback card shows."
type: "reference"
---

# Usage Data & Feedback

The TaxJar Integration sends usage data to Frappe, to make the app better. It also asks users to rate the app from time to time. This page tells you what the app sends, what it never sends, and how to turn it off.

## When the app sends usage data

The app sends usage data only when both of these are true:

- The site has a Frappe usage-data key. Frappe Cloud sites have one. A self-hosted site does not, so it sends nothing.
- **Allow Sending Usage Data for Improving Applications** is on in **System Settings**.

To stop all usage data, turn off **Allow Sending Usage Data for Improving Applications** in **System Settings**. This setting applies to all Frappe apps on the site.

## What the app sends

All usage data is about the site. No event has a user ID, a name or an email.

| Data | Example |
|---|---|
| Daily summary of the site | How many companies use TaxJar, which features are on, how many documents TaxJar calculated tax on, how many invoices synced in the last 30 days, how many invoices failed to sync, and how many calls the app made to TaxJar, by type. |
| Guided setup progress | Which setup steps were opened, saved or failed. Which setup videos were played. When the setup was finished. |
| First use | The first time TaxJar calculated tax, and the first time an invoice synced. |
| Problems | A tax calculation that TaxJar refused, and its error code. A submit that the app stopped, and the reason. |
| Actions | A bulk retry, an exemption change, an export, a nexus refresh. The app sends how many records, not which records. |
| Feedback | A score from 1 to 5, and the comment if the user wrote one. |

## What the app never sends

- Names of users, customers, companies or items.
- Email addresses, street addresses or phone numbers.
- Amounts, tax rates or document numbers.
- The TaxJar API token.

The site name and the Frappe Cloud team go with each event, as for all Frappe apps. The version numbers of the app and of Frappe also go with each event.

## The feedback card

A card "Rate the TaxJar app" shows in the TaxJar sidebar. **Give feedback** opens a short form with a score from 1 to 5 and an optional comment.

The card shows to users with the **Accounts User**, **Accounts Manager** or **System Manager** role, when:

- usage data is on, as described above,
- the guided setup is finished, and
- TaxJar calculated tax or synced an invoice on the site.

After you send a score, the card shows again 30 days later. After you close the card, it shows again 15 days later. To stop the card for good, open it and click **Do not ask me again**.

::: info Feedback is anonymous
Do not write personal information in the comment. The app removes formatting and hidden characters from the comment, and keeps the first 1,000 characters.
:::
