---
title: "Roles & Permissions: give people access to the TaxJar tasks"
description: "Give each person the ERPNext roles for their TaxJar work, see the exact rights of each task and page, and build a custom role with fewer rights."
type: "how-to"
---

# Roles & Permissions

The app uses the standard ERPNext roles. It adds no roles of its own. You give each person the roles for the work that they do.

## Pre-requisites

You need the **System Manager** role, or another role that can change users.

## Choose the roles

Find the person's work in the first column. Give all the roles in the second column.

| The person… | Give these roles |
|---|---|
| Sets up TaxJar and keeps it running (**TaxJar Manager**) | **Accounts Manager** and **Accounts User** |
| Invoices, fixes sync problems and closes the period (**TaxJar User**) | **Accounts User** |
| Also sets or clears customer exemptions, or sends customers to TaxJar | Add **Sales User** |
| Also sets the **Product Tax Category** on items | Add **Item Manager** |
| Makes quotations and sales orders only | **Sales User**. No TaxJar access is necessary. TaxJar calculates the tax for each user who can save the document. |

::: warning System Manager alone is not enough
In ERPNext, System Manager cannot open sales invoices, customers or ledger accounts. A System Manager who does TaxJar work also needs the roles in the table.
:::

The first user of a new site gets all roles in the ERPNext setup wizard. This user can do all TaxJar tasks.

## Give the roles to a user

1. Open the **User**.
2. Go to the **Roles** section.
3. Select the roles from the table.
4. Save the user.

## Personas

A persona is a type of TaxJar user. It is not a role. The app finds the persona from the rights on **TaxJar Settings**.

| Persona | Right on TaxJar Settings | Standard roles with this right |
|---|---|---|
| **TaxJar Manager** | Write | System Manager, Accounts Manager |
| **TaxJar User** | Read | System Manager, Accounts Manager, Accounts User |

The persona controls the TaxJar pages, the update buttons and the nexus notification. It gives no rights on ERPNext documents.

## Rights for each task

Each task needs read on every document type in its row, and the other rights that the row names.

| Task | Rights | Standard roles that have them |
|---|---|---|
| Do TaxJar Setup | TaxJar Settings: write. Company and Account: read. Address: read, write, create. | Accounts Manager (with Accounts User) |
| View the nexus states and the product tax categories | TaxJar Settings: read | Accounts User |
| Update the nexus states or the categories from TaxJar | TaxJar Settings: write | Accounts Manager |
| Add, change or delete product tax categories by hand | Product Tax Category: write, create, delete | Accounts Manager |
| Set the product tax category on an item | Item: write | Item Manager |
| View and export the customer list | Customer: read | Accounts User |
| Set or clear an exemption, send a customer to TaxJar | Customer: write. Company: read. | Sales User, Sales Master Manager |
| Create customers and their addresses | Customer: create. Address: create. | Sales User |
| Make quotations and sales orders with TaxJar tax | Quotation, Sales Order: write, create, submit | Sales User |
| Make sales invoices and credit notes with TaxJar tax | Sales Invoice: write, create, submit | Accounts User |
| Send a failed invoice to TaxJar again | Sales Invoice: write | Accounts User |
| View and export the transaction list | Sales Invoice: read | Accounts User |
| Read the TaxJar API Log | TaxJar API Log: read | Accounts User |
| Get the notification when the daily nexus update fails | TaxJar Settings: read | Accounts User |
| Run the version 15 invoice check | TaxJar Settings: write | Accounts Manager |

To make documents, ERPNext needs more rights than the table shows, for example on Item and Price List. Start from Sales User or Accounts User, and add what they do not have.

## Roles on the TaxJar pages

A user opens a page only when one of their roles is on the page.

| Page | Roles on the page |
|---|---|
| TaxJar Setup (`taxjar-setup`) | System Manager, Accounts Manager |
| Nexus & Product Category (`taxjar-nexus`) | System Manager, Accounts Manager, Accounts User |
| Customer Tax Exemption (`taxjar-customers`) | Accounts Manager, Accounts User |
| TaxJar Transaction Sync (`taxjar-transactions`) | Accounts Manager, Accounts User |
| TaxJar Integration workspace | System Manager, Accounts Manager, Accounts User |

The Customer Tax Exemption page opens for Accounts roles, but an exemption needs write on Customer. With the standard roles, a person who changes exemptions on this page needs an Accounts role and Sales User.

## Give fewer rights with a custom role

A standard role gives rights on more than TaxJar. For example, Sales User can also make and change quotations and sales orders. To give only the rights of one TaxJar task, make a custom role with the rights in [Rights for each task](#rights-for-each-task).

1. Make a new **Role**.
2. In **Role Permission Manager**, give the role the rights of the task rows that the person does.
3. In **Role Permission for Page and Report**, add the role to each page that the task uses.
4. Add the role to the **TaxJar Integration** workspace, so that the person sees the TaxJar app.
5. Give the role to the user.

On each migrate, the app adds System Manager, Accounts Manager and Accounts User to the workspace again if they are missing. It keeps the roles that you add.

## If a user cannot do a task

The user sees the message "You do not have {right} access to {document type}, ask your administrator to update permissions for your user." Find the task in [Rights for each task](#rights-for-each-task), and give the missing role or right.

## Work that needs no rights

The app writes these records itself: the TaxJar API Log entries, the sync status on invoices and customers, the TaxJar Sales Tax template, and the product tax categories from TaxJar.

If a user has **User Permissions** on Company, the TaxJar pages show only the documents of those companies.
