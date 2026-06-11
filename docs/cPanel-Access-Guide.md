# cPanel Access Guide — Train Drivers Academy

## Server Details

| Environment | IP Address | Purpose |
|-------------|------------|---------|
| **Production** | `13.135.200.253` | Live site (EC2 `i-0c4fb39f766dfc80d`) |
| **Staging / Dev** | `16.61.86.201` | Testing and development (EC2 `i-000d9f6aa6d1bbe5c`) |

### Database Endpoints (RDS)

These are the database server addresses used by Joomla. You will need these when configuring Joomla or connecting a database tool.

| Environment | Database Host | Database Name | Username |
|-------------|--------------|---------------|----------|
| **Production** | `tda-rds-prod.cbi6gciei7yc.eu-west-2.rds.amazonaws.com` | `joomla` | `joomla_admin` |
| **Staging** | `tda-rds-staging.cbi6gciei7yc.eu-west-2.rds.amazonaws.com` | `joomla` | `joomla_admin` |

> The database password is held securely by your system administrator. Do not store it in plain text.

---

## How to Access WHM (Web Host Manager)

WHM is the admin panel used to create accounts, manage hosting, and configure the server. You need WHM access to create new cPanel accounts.

**WHM is the top level — think of it as the "manager" of all cPanel accounts.**

### Steps to Log In to WHM

1. Open your web browser
2. Go to one of the following addresses:

   **Production:**
   ```
   https://13.135.200.253:2087
   ```

   **Staging:**
   ```
   https://16.61.86.201:2087
   ```

3. Your browser may show a security warning ("Your connection is not private"). This is normal at this stage — click **Advanced** then **Proceed** (or **Accept the risk and continue** in Firefox).

4. Log in with:
   - **Username:** `root`
   - **Password:** `TdaProd9kWx2mQ4vL!`

> **Important:** Change this password after your first login via WHM → Server Configuration → Change Root Password.

---

## How to Access cPanel

cPanel is the control panel for an individual hosting account. Each Joomla site or user has their own cPanel account.

### Steps to Log In to cPanel

1. Open your web browser
2. Go to:

   **Production:**
   ```
   https://13.135.200.253:2083
   ```

   **Staging:**
   ```
   https://16.61.86.201:2083
   ```

3. Accept the browser security warning as above.

4. Log in with the username and password for that specific account.

> **Tip:** You can also log in to a cPanel account directly from WHM without needing the password — see the section below.

---

## How to Create a New cPanel Account (in WHM)

Use this when you need to set up a new website or user.

1. Log in to **WHM** (see above)
2. In the search box on the left, type **Create a New Account**
3. Click **Create a New Account**
4. Fill in the details:
   - **Domain:** the domain for this account (e.g. `traindriversacademy.co.uk`)
   - **Username:** a short username (max 16 characters, no spaces)
   - **Password:** set a strong password, or click **Password Generator**
   - **Email:** the account owner's email address
5. Leave all other settings as default unless instructed otherwise
6. Click **Create**

The account will be ready within a few seconds.

---

## How to Log In to a cPanel Account via WHM (without the password)

Useful when you need to manage an account but don't know the password.

1. Log in to **WHM**
2. In the search box, type **List Accounts**
3. Click **List Accounts**
4. Find the account you want
5. Click the **cPanel icon** (looks like a small box) next to that account
6. You will be logged straight into that account's cPanel

---

## How to Reset a cPanel Account Password

1. Log in to **WHM**
2. Search for **List Accounts** and click it
3. Find the account and click the **+** to expand it
4. Click **Change Password**
5. Enter and confirm the new password
6. Click **Change**

---

## Port Reference

| Port | What it's for |
|------|--------------|
| `2087` | WHM (admin panel) — HTTPS |
| `2086` | WHM — HTTP (non-SSL, not recommended) |
| `2083` | cPanel — HTTPS |
| `2082` | cPanel — HTTP (non-SSL, not recommended) |
| `443` | Website — HTTPS |
| `80` | Website — HTTP |

---

## Important Notes

- **Always use the staging server for testing.** Never test new Joomla extensions, themes, or configurations directly on production.
- **Production changes should be promoted from staging**, not made directly.
- If you see a browser SSL warning, it is safe to proceed — this will be resolved once a proper SSL certificate is installed for the domain.
- Do not share the root password. Each team member should have their own cPanel account created for them.

---

## Troubleshooting

**"This site can't be reached" / page won't load**
- cPanel may still be installing (can take up to 20 minutes after first boot). Try again shortly.
- Make sure you are using `https://` not `http://` and the correct port.

**"SSL certificate error" / browser warning**
- This is expected until a domain SSL certificate is set up. Click through the warning to proceed.

**Forgot the root WHM password**
- Contact your system administrator — this is reset via the AWS Lightsail console.

---

*Last updated: June 2026 | Environment: AWS EC2 CloudLinux 10, eu-west-2 (London)*
