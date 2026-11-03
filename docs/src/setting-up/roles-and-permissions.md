---
title: "Roles & Permissions"
description: "Give each person the ERPNext roles for their TaxJar work, see the exact rights of each task and page, and build a custom role with fewer rights."
type: "how-to"
---

# Roles & Permissions

TaxJar app doesn't publish its own roles, rather uses standard roles defined by ERPNext to carry out operations.

## Personas

A persona describes the TaxJar operations that a person carries out. It is not a role: it controls only the TaxJar pages, the update buttons and the nexus notification, and gives no rights on ERPNext documents.

Choose the persona that fits the person's work, then give the person the role in its tab.

:::tabs
== TaxJar Manager
Sets up TaxJar and keeps it running: the guided setup, the nexus states and the product tax categories.

**Role:** <Badge type="info" text="Accounts Manager" /> gives write access to **TaxJar Settings**.
== TaxJar User
Works with TaxJar every day: invoices, sync problems and the period close.

**Role:** <Badge type="info" text="Accounts User" /> gives read access to **TaxJar Settings**.
:::

## Roles for Each Task

Find each task that the person carries out, and give the person the roles of that task. A person who carries out tasks in more than one tab needs the roles from each tab.

:::tabs
== Setting Up
| Task | Role |
|---|---|
| Do TaxJar Setup | <Badge type="info" text="Accounts Manager" /> and <Badge type="info" text="Accounts User" /> |
| Update the nexus states or the product tax categories from TaxJar | <Badge type="info" text="Accounts Manager" /> |
| Add, change or delete product tax categories by hand | <Badge type="info" text="Accounts Manager" /> |
| Run the version 15 invoice check | <Badge type="info" text="Accounts Manager" /> |
| View the nexus states and the product tax categories | <Badge type="info" text="Accounts User" /> or <Badge type="info" text="Accounts Manager" /> |
== Tax Exemptions
| Task | Role |
|---|---|
| Set or clear a customer exemption, or send a customer to TaxJar | <Badge type="info" text="Accounts User" /> or <Badge type="info" text="Accounts Manager" />, and <Badge type="info" text="Sales User" /> |
| View and export the customer list | <Badge type="info" text="Accounts User" /> or <Badge type="info" text="Accounts Manager" /> |
| Create customers and their addresses | <Badge type="info" text="Sales User" /> |
| Set the product tax category on an item | <Badge type="info" text="Item Manager" /> |
== Sales & Invoices
| Task | Role |
|---|---|
| Make quotations and sales orders with TaxJar tax | <Badge type="info" text="Sales User" /> |
| Make sales invoices, credit notes and debit notes with TaxJar tax | <Badge type="info" text="Accounts User" /> or <Badge type="info" text="Accounts Manager" /> |
| Send a failed invoice to TaxJar again | <Badge type="info" text="Accounts User" /> or <Badge type="info" text="Accounts Manager" /> |
| View and export the transaction list | <Badge type="info" text="Accounts User" /> or <Badge type="info" text="Accounts Manager" /> |
== Troubleshoot
| Task | Role |
|---|---|
| Read the TaxJar API Log | <Badge type="info" text="Accounts User" /> or <Badge type="info" text="Accounts Manager" /> |
| Get the notification when the daily nexus update fails | <Badge type="info" text="Accounts User" /> or <Badge type="info" text="Accounts Manager" /> |
:::

## Assign Roles to a User

If you cannot change users in ERPNext, ask your ERPNext administrator to assign the roles.

1. Open the **User**.
2. Go to the **Roles** section.
3. Select the roles from [Roles for Each Task](#roles-for-each-task).
4. Save the user.

![The Roles section of a User form with Accounts User and Sales User ticked](/images/user-roles-section.webp)

## Permissions by Task

To make a custom role, give it the permissions with a dot in the row of each task.

:::tabs
== Setting Up
| Task | DocType | Read | Write | Create | Submit | Delete |
|---|---|:-:|:-:|:-:|:-:|:-:|
| Do TaxJar Setup | TaxJar Settings | ● | ● |  |  |  |
|  | Company | ● |  |  |  |  |
|  | Account | ● |  |  |  |  |
|  | Address | ● | ● | ● |  |  |
| Update the nexus states or the product tax categories from TaxJar | TaxJar Settings | ● | ● |  |  |  |
| Add, change or delete product tax categories by hand | Product Tax Category | ● | ● | ● |  | ● |
| Run the version 15 invoice check | TaxJar Settings | ● | ● |  |  |  |
| View the nexus states and the product tax categories | TaxJar Settings | ● |  |  |  |  |
== Tax Exemptions
| Task | DocType | Read | Write | Create | Submit | Delete |
|---|---|:-:|:-:|:-:|:-:|:-:|
| Set or clear a customer exemption, or send a customer to TaxJar | Customer | ● | ● |  |  |  |
|  | Company | ● |  |  |  |  |
| View and export the customer list | Customer | ● |  |  |  |  |
| Create customers and their addresses | Customer | ● |  | ● |  |  |
|  | Address | ● |  | ● |  |  |
| Set the product tax category on an item | Item | ● | ● |  |  |  |
== Sales & Invoices
| Task | DocType | Read | Write | Create | Submit | Delete |
|---|---|:-:|:-:|:-:|:-:|:-:|
| Make quotations and sales orders with TaxJar tax | Quotation | ● | ● | ● | ● |  |
|  | Sales Order | ● | ● | ● | ● |  |
| Make sales invoices, credit notes and debit notes with TaxJar tax | Sales Invoice | ● | ● | ● | ● |  |
| Send a failed invoice to TaxJar again | Sales Invoice | ● | ● |  |  |  |
| View and export the transaction list | Sales Invoice | ● |  |  |  |  |
== Troubleshoot
| Task | DocType | Read | Write | Create | Submit | Delete |
|---|---|:-:|:-:|:-:|:-:|:-:|
| Read the TaxJar API Log | TaxJar API Log | ● |  |  |  |  |
| Get the notification when the daily nexus update fails | TaxJar Settings | ● |  |  |  |  |
:::

To make documents, ERPNext needs more rights than the table shows, for example on Item and Price List. Start from Sales User or Accounts User, and add what they do not have.

## Page Access

A user opens a page only when one of their roles is on the page.

| Page | Page ID | Accounts Manager | Accounts User |
|---|---|:-:|:-:|
| TaxJar Setup | `taxjar-setup` | ● |  |
| Nexus & Product Category | `taxjar-nexus` | ● | ● |
| Customer Tax Exemption | `taxjar-customers` | ● | ● |
| TaxJar Transaction Sync | `taxjar-transactions` | ● | ● |
| TaxJar Integration workspace | - | ● | ● |

The Customer Tax Exemption page opens for Accounts roles, but an exemption needs write on Customer. With the standard roles, a person who changes exemptions on this page needs an Accounts role and Sales User.

## Custom Roles

A standard role gives permissions on more than TaxJar. For example, Sales User can also make and change quotations and sales orders. A custom role gives only the permissions of the TaxJar tasks that the person carries out.

::: tip
If you cannot make roles in ERPNext, ask your ERPNext administrator to make the custom role.
:::

1. Make a new **Role**.
2. In **Role Permission Manager**, give the role the permissions of each task that the person carries out. The permissions are in [Permissions by Task](#permissions-by-task).
3. In **Role Permission for Page and Report**, add the role to each page that the tasks use. The page IDs are in [Page Access](#page-access).
4. Add the role to the **TaxJar Integration** workspace, so that the person sees the TaxJar app. App updates keep this change.
5. Give the role to the user, as in [Assign Roles to a User](#assign-roles-to-a-user).

## Permission Errors

When a user does not have a permission, ERPNext shows this message:

> You do not have {right} access to {document type}, ask your administrator to update permissions for your user.

Find the task in [Permissions by Task](#permissions-by-task), and give the missing role or permission.

## Automatic Updates

The app writes these records itself: the TaxJar API Log entries, the sync status on invoices and customers, the TaxJar Sales Tax template, and the product tax categories from TaxJar.

If a user has **User Permissions** on Company, the TaxJar pages show only the documents of those companies.
