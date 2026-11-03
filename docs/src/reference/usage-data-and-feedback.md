---
title: "Usage Data & Feedback"
description: "The usage data that the TaxJar Integration sends to Frappe, the data that it never sends, how to turn usage data off, and when the feedback card shows."
type: "reference"
---

# Usage Data & Feedback

The TaxJar Integration sends usage data to Frappe, to make the app better. It also asks users to rate the app from time to time.

## When the App Sends Data

The app sends usage data only when both of these are true:

- The site has a Frappe usage-data key. Frappe Cloud sites have one. A self-hosted site does not, so it sends nothing.
- **Allow Sending Usage Data for Improving Applications** is on in **System Settings**.

::: tip
To stop all usage data, turn off **Allow Sending Usage Data for Improving Applications** in **System Settings**. This setting applies to all Frappe apps on the site.
:::

## What the App Sends

All usage data is about the site. No event has a user ID, a name or an email.

| Data | Example |
|---|---|
| **Daily Summary** | How many companies use TaxJar, which features are on, how many documents TaxJar calculated tax on, how many invoices synced in the last 30 days, how many invoices failed to sync, and how many calls the app made to TaxJar, by type. |
| **Setup Progress** | Which setup steps were opened, saved or failed. Which setup videos were played. When the setup was finished. |
| **First Use** | The first time TaxJar calculated tax, and the first time an invoice synced. |
| **Problems** | A tax calculation that TaxJar refused, and its error code. A submit that the app stopped, and the reason. |
| **Actions** | A bulk retry, an exemption change, an export, a nexus refresh. The app sends how many records, not which records. |
| **Feedback** | A score from 1 to 5, and the comment if the user wrote one. |

The site name, the Frappe Cloud team and the version numbers of the app and of Frappe go with each event, as for all Frappe apps.

## What the App Never Sends

| Data | Example |
|---|---|
| **Names** | Users, customers, companies and items |
| **Contact Details** | Email addresses, street addresses and phone numbers |
| **Document Data** | Amounts, tax rates and document numbers |
| **Credentials** | The TaxJar API token |

## Feedback Card

A card **Rate the TaxJar app** shows in the TaxJar sidebar. **Give feedback** opens a short form with a score from 1 to 5 and an optional comment.

**Who sees it:** <Badge type="info" text="Accounts User" /> and <Badge type="info" text="Accounts Manager" />

**When it shows:** all three of these are true.

- Usage data is on. Refer to [When the App Sends Data](#when-the-app-sends-data).
- The guided setup is finished.
- TaxJar calculated tax or synced an invoice on the site.

**When it shows again:**

| After You | The Card Shows Again |
|---|---|
| Send a score | 30 days later |
| Close the card | 15 days later |
| Click **Do not ask me again** | Never |

::: info Feedback Is Anonymous
Do not write personal information in the comment. The app removes formatting and hidden characters from the comment, and keeps the first 1,000 characters.
:::
