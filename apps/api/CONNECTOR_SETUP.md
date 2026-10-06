# Connector Setup Handbook

How to register each of the 52 connectors in `services/mcp/registry.py` and get real credentials into this app. Read this section before touching anything below.

## Two kinds of connector

**OAuth2** — the user clicks "Connect" in the app, logs into the provider, approves access, and is redirected back. This needs *you* (the operator) to register one OAuth app per provider in that provider's developer dashboard, and put its **Client ID / Client Secret into `apps/api/.env`** (never per-user — one app serves everyone). The exact env var names are given per-connector below and already have empty placeholders in `.env`.

**API key** — the provider has no practical per-user consent redirect for this use case (a static secret the user copies from their own account dashboard instead — e.g. a Stripe secret key, AWS access keys). There is **nothing to put in `.env`** for these — each user pastes their own value(s) directly into the app's Connectors page, which encrypts and stores them per-user. The "credential fields" listed below are what the Connectors page will ask that user to paste.

## Redirect URI

Every OAuth2 connector below needs your redirect URI registered on the provider's side. Use:
- Local dev: `http://localhost:5173/connectors`
- Production: `https://<your-domain>/connectors`

A few providers have quirks (HTTPS-only, no localhost, etc.) — called out per connector below.

## Status: "Ready" vs "Actions coming soon"

Every connector's **Connect/Disconnect flow works today** — registering the OAuth app or pasting an API key is never wasted effort. But only **13 of 52** currently have a real tool-execution server wired up (`mcp_status: "ready"` in the registry); for the other 39, Claude will correctly report "not wired up yet" rather than silently failing if you try to use them in a prompt. The Connectors page shows an "Actions coming soon" badge on these. Building the remaining servers is the natural next phase — `mcp_notes` in the registry entry (and the "MCP server" line below) says what to build or verify for each.

| Status | Count | Meaning |
|---|---|---|
| ✅ Ready | 13 | Connect, then prompt Claude — real tool calls happen today |
| 🔧 Actions coming soon | 39 | Connect today; a tool server still needs to be built/verified |

## Quick reference

| Connector | Category | Auth | Status | Where credentials go |
|---|---|---|---|---|
| Google Calendar | Calendar & Scheduling | OAuth2 | ✅ | `.env` (reuses `GOOGLE_CLIENT_ID/SECRET`) |
| GitHub | Developer Tools | OAuth2 | ✅ | `.env`: `GITHUB_MCP_CLIENT_ID/SECRET` |
| Slack | Communication | OAuth2 | ✅ | `.env`: `SLACK_CLIENT_ID/SECRET` |
| Notion | Productivity & Docs | OAuth2 | ✅ | `.env`: `NOTION_CLIENT_ID/SECRET` |
| Gmail | Communication | OAuth2 | ✅ | `.env` (reuses `GOOGLE_CLIENT_ID/SECRET`) |
| Microsoft Teams | Communication | OAuth2 | 🔧 | `.env`: `MS_TEAMS_CLIENT_ID/SECRET` |
| Discord | Communication | OAuth2 | 🔧 | `.env`: `DISCORD_CLIENT_ID/SECRET` |
| Zoom | Communication | OAuth2 | 🔧 | `.env`: `ZOOM_CLIENT_ID/SECRET` |
| Microsoft Outlook (Mail) | Communication | OAuth2 | 🔧 | `.env`: `MS_OUTLOOK_CLIENT_ID/SECRET` |
| Telegram | Communication | API key | 🔧 | App UI: bot token |
| Twilio | Communication | API key | 🔧 | App UI: Account SID + API Key SID/Secret |
| WhatsApp Business | Communication | API key | 🔧 | App UI: access token + phone number ID + WABA ID |
| Google Docs | Productivity & Docs | OAuth2 | 🔧 | `.env` (reuses `GOOGLE_CLIENT_ID/SECRET`) |
| Google Sheets | Productivity & Docs | OAuth2 | 🔧 | `.env` (reuses `GOOGLE_CLIENT_ID/SECRET`) |
| Google Drive | Productivity & Docs | OAuth2 | 🔧 | `.env` (reuses `GOOGLE_CLIENT_ID/SECRET`) |
| Confluence | Productivity & Docs | OAuth2 | ✅ | `.env`: `ATLASSIAN_CLIENT_ID/SECRET` |
| Microsoft OneDrive | Productivity & Docs | OAuth2 | 🔧 | `.env`: `MS_GRAPH_CLIENT_ID/SECRET` |
| Microsoft SharePoint | Productivity & Docs | OAuth2 | 🔧 | `.env` (reuses `MS_GRAPH_CLIENT_ID/SECRET`) |
| Dropbox | Productivity & Docs | OAuth2 | 🔧 | `.env`: `DROPBOX_APP_KEY/SECRET` |
| Box | Productivity & Docs | OAuth2 | 🔧 | `.env`: `BOX_CLIENT_ID/SECRET` |
| Asana | Project Management | OAuth2 | ✅ | `.env`: `ASANA_CLIENT_ID/SECRET` |
| Linear | Project Management | OAuth2 | ✅ | `.env`: `LINEAR_CLIENT_ID/SECRET` |
| Jira | Project Management | OAuth2 | ✅ | `.env`: `ATLASSIAN_CLIENT_ID/SECRET` |
| Trello | Project Management | API key | 🔧 | App UI: API key + token |
| ClickUp | Project Management | OAuth2 | 🔧 | `.env`: `CLICKUP_CLIENT_ID/SECRET` |
| monday.com | Project Management | OAuth2 | ✅ | `.env`: `MONDAY_CLIENT_ID/SECRET` |
| Basecamp | Project Management | OAuth2 | 🔧 | `.env`: `BASECAMP_CLIENT_ID/SECRET` |
| Airtable | Project Management | OAuth2 | 🔧 | `.env`: `AIRTABLE_CLIENT_ID/SECRET` |
| GitLab | Developer Tools | OAuth2 | 🔧 | `.env`: `GITLAB_CLIENT_ID/SECRET` |
| Bitbucket | Developer Tools | OAuth2 | 🔧 | `.env`: `BITBUCKET_CLIENT_ID/SECRET` |
| Vercel | Developer Tools | API key | 🔧 | App UI: access token |
| AWS | Developer Tools | API key | 🔧 | App UI: access key ID + secret + region |
| Azure | Developer Tools | API key | 🔧 | App UI: tenant/client ID + secret + subscription ID |
| GCP | Developer Tools | API key | 🔧 | App UI: project ID + service account JSON |
| CircleCI | Developer Tools | API key | 🔧 | App UI: API token |
| Sentry | Developer Tools | OAuth2 | ✅ | `.env`: `SENTRY_CLIENT_ID/SECRET` |
| HubSpot | CRM & Support | OAuth2 | ✅ | `.env`: `HUBSPOT_CLIENT_ID/SECRET` |
| Salesforce | CRM & Support | OAuth2 | 🔧 | `.env`: `SALESFORCE_CLIENT_ID/SECRET` |
| Intercom | CRM & Support | OAuth2 | ✅ | `.env`: `INTERCOM_CLIENT_ID/SECRET` |
| Zendesk | CRM & Support | OAuth2 | 🔧 | `.env`: `ZENDESK_CLIENT_ID/SECRET` |
| Freshdesk | CRM & Support | API key | 🔧 | App UI: API key + domain |
| Mailchimp | CRM & Support | OAuth2 | 🔧 | `.env`: `MAILCHIMP_CLIENT_ID/SECRET` |
| SendGrid | CRM & Support | API key | 🔧 | App UI: API key |
| DocuSign | CRM & Support | OAuth2 | 🔧 | `.env`: `DOCUSIGN_CLIENT_ID/SECRET` |
| Stripe | Commerce & Finance | API key | 🔧 | App UI: secret key |
| PayPal | Commerce & Finance | API key | 🔧 | App UI: client ID + secret + mode |
| Shopify | Commerce & Finance | API key | 🔧 | App UI: shop domain + admin API token |
| QuickBooks | Commerce & Finance | OAuth2 | 🔧 | `.env`: `QUICKBOOKS_CLIENT_ID/SECRET` |
| Twitter/X | Social Media | OAuth2 | 🔧 | `.env`: `X_CLIENT_ID/SECRET` |
| LinkedIn | Social Media | OAuth2 | 🔧 | `.env` (reuses `LINKEDIN_CLIENT_ID/SECRET`) |
| Reddit | Social Media | OAuth2 | 🔧 | `.env`: `REDDIT_CLIENT_ID/SECRET` |
| Google Analytics | Analytics | OAuth2 | 🔧 | `.env` (reuses `GOOGLE_CLIENT_ID/SECRET`) |

---

## Calendar & Scheduling

### Google Calendar ✅ Ready
Lets Claude read and manage events on your calendar.
- **Dashboard**: [console.cloud.google.com/apis/credentials](https://console.cloud.google.com/apis/credentials) — already set up (reuses the app's existing login credentials).
- Nothing to do — this one works out of the box once you connect it in the app.

---

## Communication

### Gmail ✅ Ready
Read and send email through your Gmail account.
- **Dashboard**: same Google Cloud project as Calendar — [console.cloud.google.com/apis/credentials](https://console.cloud.google.com/apis/credentials).
- Enable the **Gmail API** under APIs & Services → Library (if not already).
- No new `.env` entries — reuses `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`.
- Gotcha: `gmail.send`/`gmail.readonly` are Google "sensitive" scopes — while your OAuth consent screen is in Testing mode, only up to 100 manually-added test users can connect, and their refresh tokens expire after 7 days. Move to "In production" (a quick Google review) to lift this for real users.

### Microsoft Teams 🔧
Read and post messages in your Teams chats/channels.
- **Dashboard**: [entra.microsoft.com](https://entra.microsoft.com) → Identity → Applications → App registrations → New registration.
- Choose "Accounts in any organizational directory and personal Microsoft accounts". Add a **Web** platform redirect URI. Create a client secret (Certificates & secrets) and copy it immediately — shown once.
- Scopes: `offline_access`, `User.Read`, `Team.ReadBasic.All`, `Channel.ReadBasic.All`, `ChannelMessage.Send`, `Chat.ReadWrite`.
- Paste into `.env`: `MS_TEAMS_CLIENT_ID`, `MS_TEAMS_CLIENT_SECRET`.
- Gotcha: some tenants require admin consent for these scopes regardless of docs saying otherwise.

### Discord 🔧
Send/read messages in Discord servers you install the bot into.
- **Dashboard**: [discord.com/developers/applications](https://discord.com/developers/applications) → New Application.
- Under OAuth2 → General, copy Client ID/Secret; under OAuth2 → Redirects, add your redirect URI.
- Under the **Bot** tab, create a bot and copy its **Bot Token** separately (keep secret) — this is a platform-wide token, not per-user.
- Paste into `.env`: `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`. The bot token will need its own env var once the tool server is built (not yet in the registry).
- Gotcha: the OAuth flow only lets a user pick which server to install the bot into — actual sending uses the static bot token, not a per-user token.

### Zoom 🔧
Create/manage Zoom meetings on your behalf.
- **Dashboard**: [marketplace.zoom.us/develop/create](https://marketplace.zoom.us/develop/create) → General App.
- Copy Client ID/Secret from Basic Information. Add your redirect URL under OAuth allow lists (must be HTTPS — plain `http://localhost` is rejected; use `http://127.0.0.1:{port}/...` for local testing).
- Paste into `.env`: `ZOOM_CLIENT_ID`, `ZOOM_CLIENT_SECRET`.
- Gotcha: refresh tokens rotate on every use and expire after 90 days — must persist the new one each time.

### Microsoft Outlook (Mail) 🔧
Read/send email through your Outlook/Microsoft 365 mailbox.
- **Dashboard**: same as Teams ([entra.microsoft.com](https://entra.microsoft.com)) — can reuse that same app registration if you like, or make a separate one.
- Scopes: `offline_access`, `User.Read`, `Mail.Read`, `Mail.Send`.
- Paste into `.env`: `MS_OUTLOOK_CLIENT_ID`, `MS_OUTLOOK_CLIENT_SECRET`.

### Telegram 🔧
Send/receive messages as a bot you add to chats/groups.
- **No web dashboard** — open Telegram, message **@BotFather**, send `/newbot`, follow the prompts.
- BotFather replies with a bot token (format `123456789:ABC-...`) — paste that into the app's Connectors page (**not** `.env`).
- Gotcha: bots can't message a user first — the user must message the bot first. Send `/setprivacy` to BotFather and disable privacy mode if the bot needs to read all group messages, not just mentions.

### Twilio 🔧
Send SMS/WhatsApp messages and manage calls.
- **Dashboard**: [console.twilio.com](https://console.twilio.com) → Account SID is on the main dashboard. Go to Account → API keys & tokens → Create API key (Standard).
- Copy the Account SID, API Key SID, and API Key Secret — paste all three into the app's Connectors page (**not** `.env`).
- Gotcha: trial accounts can only message pre-verified numbers; sending real SMS in the US may need A2P 10DLC registration.

### WhatsApp Business 🔧
Send/receive WhatsApp Business messages via Meta's Cloud API.
- **Dashboard**: [developers.facebook.com/apps](https://developers.facebook.com/apps) → add the WhatsApp product. Note the test Phone Number ID and WABA ID under WhatsApp → API Setup.
- Go to [business.facebook.com/settings](https://business.facebook.com/settings) → System Users → create one, assign it the app + WABA with Full Control, generate a token with `whatsapp_business_management`/`whatsapp_business_messaging` permissions (Never Expire or 60-day).
- Paste the access token, phone number ID, and WABA ID into the app's Connectors page (**not** `.env`).
- Gotcha: messaging outside a user-initiated 24h window needs pre-approved templates; scaling past development use generally requires Meta Business Verification.

---

## Productivity & Docs

### Google Docs / Google Sheets / Google Drive 🔧
Read/create/edit docs, spreadsheets, and files.
- **Dashboard**: same Google Cloud project as Calendar/Gmail. Enable the Docs API, Sheets API, and/or Drive API as needed.
- No new `.env` entries — all three reuse `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` (only the scope differs per connector: `.../auth/documents`, `.../auth/spreadsheets`, `.../auth/drive.file`).
- Gotcha: `drive.file` only sees files your app created or the user explicitly picked — it will NOT list pre-existing Drive files. Avoid the broader `drive`/`drive.readonly` scopes unless necessary — they're "Restricted" and require a paid Google security assessment past 100 users.

### Confluence ✅ Ready / Jira ✅ Ready
Search/read/create Confluence pages; manage Jira issues.
- **Dashboard**: [developer.atlassian.com/console/myapps](https://developer.atlassian.com/console/myapps) → Create → OAuth 2.0 integration. Add the Jira and/or Confluence API permissions and your redirect URL.
- One app covers both — paste into `.env`: `ATLASSIAN_CLIENT_ID`, `ATLASSIAN_CLIENT_SECRET`.
- Gotcha: Cloud only (no Server/Data Center). Must include `offline_access` scope or no refresh token is issued; after login you must call `accessible-resources` to get the user's `cloudId` before any API call works.

### Microsoft OneDrive 🔧 / SharePoint 🔧
List/read/upload files; manage SharePoint docs/lists.
- **Dashboard**: [entra.microsoft.com](https://entra.microsoft.com) → new App registration (or reuse the Teams one). Add a Web redirect URI, create a client secret, add Graph permissions `Files.ReadWrite` (OneDrive) and/or `Sites.ReadWrite.All` (SharePoint).
- One app covers both — paste into `.env`: `MS_GRAPH_CLIENT_ID`, `MS_GRAPH_CLIENT_SECRET`.
- Gotcha: SharePoint only exists for work/school tenants (not personal accounts), and `Sites.ReadWrite.All` may need an org admin's consent.

### Dropbox 🔧
List/read/upload/manage files.
- **Dashboard**: [dropbox.com/developers/apps](https://www.dropbox.com/developers/apps) → Create app → Scoped access → Full Dropbox or App folder.
- On the Permissions tab, check the scopes you need (e.g. `files.content.read/write`) and Submit — this must happen before they can be requested in the OAuth URL. Add your redirect URI under Settings → OAuth 2.
- Paste into `.env`: `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`.
- Gotcha: pass `token_access_type=offline` (already set in the registry) or you won't get a refresh token.

### Box 🔧
List/read/upload/manage files/folders.
- **Dashboard**: [account.box.com/developers/console](https://account.box.com/developers/console) → Create New App → Custom App → User Authentication (OAuth 2.0).
- Set the redirect URI under Configuration, check "Read and write all files and folders" under Application Scopes.
- Paste into `.env`: `BOX_CLIENT_ID`, `BOX_CLIENT_SECRET`.
- Gotcha: Box's own hosted MCP server exists but is admin/enterprise-gated — this app's OAuth token is meant to back a custom-built tool server instead (see registry `mcp_notes`).

---

## Project Management

### Asana ✅ Ready
Read/manage tasks, projects, and comments.
- **Dashboard**: [app.asana.com/0/my-apps](https://app.asana.com/0/my-apps) → Create new app. Add your redirect URI under the OAuth tab.
- Paste into `.env`: `ASANA_CLIENT_ID`, `ASANA_CLIENT_SECRET`.
- Gotcha: omitting the `scope` parameter grants full account access by default — the registry already requests specific scopes.

### Linear ✅ Ready
Read/manage issues, projects, cycles, comments.
- **Dashboard**: [linear.app/settings/api/applications/new](https://linear.app/settings/api/applications/new) → Create new OAuth application.
- Paste into `.env`: `LINEAR_CLIENT_ID`, `LINEAR_CLIENT_SECRET`.

### Trello 🔧
Read/manage boards, lists, and cards.
- **No standard OAuth2** — Trello uses an API key + a separate per-user token.
- **Dashboard**: [trello.com/power-ups/admin](https://trello.com/power-ups/admin) → create a Power-Up, open its API Key tab, generate a key, and add your app's return URL to its allow-list.
- The user then visits `https://trello.com/1/authorize?expiration=never&name=YourApp&scope=read,write&response_type=token&key={your_api_key}&return_url={your_redirect}`, approves, and the token comes back in the URL — paste both the API key and the resulting token into the app's Connectors page (**not** `.env`).

### ClickUp 🔧
Read/manage tasks, lists, docs.
- **Dashboard** (must be a Workspace owner/admin): avatar → Settings → Apps → Create new app. Add your redirect URL.
- Paste into `.env`: `CLICKUP_CLIENT_ID`, `CLICKUP_CLIENT_SECRET`.
- Gotcha: no granular scopes — grants whatever permission level the authorizing user already has in the workspace they pick.

### monday.com ✅ Ready
Read/manage boards, items, updates.
- **Dashboard**: [monday.com/developers/apps](https://monday.com/developers/apps) → Create app → OAuth tab → add redirect URL + scopes.
- Paste into `.env`: `MONDAY_CLIENT_ID`, `MONDAY_CLIENT_SECRET`.
- Gotcha: monday.com also ships this MCP preinstalled on every account — a workspace admin may need to enable it under Admin → Permissions → AI Connectors.

### Basecamp 🔧
Read/manage to-dos, messages, schedule items.
- **Dashboard**: [launchpad.37signals.com/integrations](https://launchpad.37signals.com/integrations) → register a new integration.
- Paste into `.env`: `BASECAMP_CLIENT_ID`, `BASECAMP_CLIENT_SECRET`.
- Gotcha: every API request needs a descriptive `User-Agent` header with your app name + a contact email, or Basecamp may reject/throttle it.

### Airtable 🔧
Read/manage bases, tables, records.
- **Dashboard**: [airtable.com/create/oauth](https://airtable.com/create/oauth) → register an OAuth integration.
- Paste into `.env`: `AIRTABLE_CLIENT_ID`, `AIRTABLE_CLIENT_SECRET`.
- ⚠️ **Engine gap**: Airtable *requires* PKCE on every authorize request — this isn't implemented in `oauth_service.py` yet, so this connector needs that engine change before it'll actually work, not just a tool server.

---

## Developer Tools

### GitHub ✅ Ready
Create issues/PRs, search code, manage repos.
- **Dashboard**: [github.com/settings/developers](https://github.com/settings/developers) → New OAuth App (separate from the app's own login OAuth app).
- Paste into `.env`: `GITHUB_MCP_CLIENT_ID`, `GITHUB_MCP_CLIENT_SECRET`.

### GitLab 🔧
Read/manage projects, issues, merge requests, repo content.
- **Dashboard**: [gitlab.com/-/user_settings/applications](https://gitlab.com/-/user_settings/applications) → Add new application, check Confidential, select scopes.
- Paste into `.env`: `GITLAB_CLIENT_ID`, `GITLAB_CLIENT_SECRET`.
- Gotcha: self-managed GitLab instances use their own domain instead of gitlab.com for the authorize/token URLs.

### Bitbucket 🔧
Read/manage repos, pull requests, pipelines.
- **Dashboard**: Workspace settings → OAuth consumers → Add consumer. Set the Callback URL, check "This is a private consumer", set permissions.
- Paste into `.env`: `BITBUCKET_CLIENT_ID`, `BITBUCKET_CLIENT_SECRET`.

### Vercel 🔧
Inspect/manage projects, deployments, env vars.
- **Dashboard**: [vercel.com/account/tokens](https://vercel.com/account/tokens) → Create Token.
- Paste the token into the app's Connectors page (**not** `.env`).
- Gotcha: Vercel's real OAuth app flow exists but deployment-management permissions are still in private beta — a Personal Access Token is the practical path today.

### AWS 🔧
Call AWS APIs (S3, EC2, CloudWatch, Bedrock, etc.) with your own credentials.
- **Dashboard**: AWS Console → IAM → Users → create a dedicated user (not root) → attach a **least-privilege** policy (only the specific actions needed) → Security credentials tab → Create access key ("Third-party service").
- Paste the Access Key ID, Secret Access Key, and your default region into the app's Connectors page (**not** `.env`).
- ⚠️ Use a narrow IAM policy — never `AdministratorAccess`. These keys don't expire by default; rotate periodically.

### Azure 🔧
Call Azure APIs with a service principal from your own tenant.
- **Dashboard**: [portal.azure.com](https://portal.azure.com) → Microsoft Entra ID → App registrations → New registration. Copy the Application (client) ID and Directory (tenant) ID. Create a client secret under Certificates & secrets.
- Grant it a **narrow** built-in role (e.g. "Storage Blob Data Reader") scoped to a specific resource group, via Access control (IAM) on that resource — never Owner/Contributor at subscription scope.
- Paste tenant ID, client ID, client secret, and subscription ID into the app's Connectors page (**not** `.env`).
- Gotcha: the client secret has a hard expiration (you choose, up to ~24 months) — track and rotate before it lapses.

### GCP 🔧
Call GCP APIs (Cloud SQL, BigQuery, Storage, etc.) with a service account from your own project.
- **Dashboard**: [console.cloud.google.com/iam-admin/serviceaccounts](https://console.cloud.google.com/iam-admin/serviceaccounts) → Create Service Account → grant a narrow predefined role (not Owner/Editor) → Keys tab → Add Key → JSON.
- Paste your project ID and the downloaded JSON key's contents into the app's Connectors page (**not** `.env`).
- Gotcha: the JSON key never expires and is a full bearer credential — store carefully, rotate periodically.

### CircleCI 🔧
Inspect/manage pipelines, workflows, job runs.
- **Dashboard**: [app.circleci.com/settings/user/tokens](https://app.circleci.com/settings/user/tokens) → Create New Token.
- Paste the token into the app's Connectors page (**not** `.env`).
- Gotcha: CircleCI does have an OAuth2 flow, but it requires a localhost-only redirect (built for CLIs) — not usable from a hosted web app, hence the Personal API Token path.

### Sentry ✅ Ready
Read/triage issues, events, project data.
- **Dashboard**: [sentry.io/settings/account/api/applications](https://sentry.io/settings/account/api/applications/) → Create New Application. Keep "Confidential" selected, add your redirect URI.
- Paste into `.env`: `SENTRY_CLIENT_ID`, `SENTRY_CLIENT_SECRET`.

---

## CRM & Support

### HubSpot ✅ Ready
Read/write contacts, companies, deals, tickets.
- **Dashboard**: [developers.hubspot.com](https://developers.hubspot.com) → create a free developer account → create a **Public app** (not Private — OAuth needs Public). Add your redirect URL and scopes on the Auth tab.
- Paste into `.env`: `HUBSPOT_CLIENT_ID`, `HUBSPOT_CLIENT_SECRET`.
- Gotcha: to test without a full Marketplace listing/review, allowlist your own HubSpot account under the app's install settings (up to 10 accounts) — fine for personal/internal use.

### Salesforce 🔧
Query/modify leads, accounts, opportunities, cases.
- **Dashboard**: inside your own Salesforce org (requires admin rights) → Setup → App Manager → New Connected App. Set the Callback URL, check Enable OAuth Settings, select scopes. Wait 2-10 minutes after saving for it to activate, then open it again to copy the Consumer Key/Secret.
- Paste into `.env`: `SALESFORCE_CLIENT_ID`, `SALESFORCE_CLIENT_SECRET`.
- Gotcha: sandbox orgs authorize against `test.salesforce.com`, not `login.salesforce.com` — the registry's static URL only covers production; swap it manually if testing against a sandbox.

### Intercom ✅ Ready
Read/respond to conversations, manage contacts/companies.
- **Dashboard**: Intercom Developer Hub → New app → Authentication page → toggle "Use OAuth", add redirect URL and permissions.
- Paste into `.env`: `INTERCOM_CLIENT_ID`, `INTERCOM_CLIENT_SECRET`.
- Gotcha: only supports US-hosted workspaces today — EU/AU workspaces need a different authorize URL (see registry `mcp_notes`).

### Zendesk 🔧
Read/manage support tickets, users, help center content.
- **Dashboard**: `https://{your-subdomain}.zendesk.com/admin/apps-integrations/apis/zendesk-api/oauth_clients` (as an admin) → Add OAuth client. Copy the secret immediately — shown once.
- Paste into `.env`: `ZENDESK_CLIENT_ID`, `ZENDESK_CLIENT_SECRET`.
- ⚠️ **Engine gap**: Zendesk's authorize/token URLs are templated per customer subdomain (`{subdomain}.zendesk.com`) — the registry's static-URL flow doesn't support that yet; needs a small engine change (a per-connection subdomain field) before this one truly works.

### Freshdesk 🔧
Read/manage tickets, contacts, agents.
- **Dashboard**: your Freshdesk account → profile picture → Profile settings → View API Key.
- Paste the API key and your Freshdesk domain (e.g. `yourcompany.freshdesk.com`) into the app's Connectors page (**not** `.env`).
- Gotcha: the key is scoped to one agent's own permissions, not account-wide.

### Mailchimp 🔧
Manage audiences, campaigns, templates.
- **Dashboard**: `https://{your-datacenter}.admin.mailchimp.com/account/oauth2/` → Register An App.
- Paste into `.env`: `MAILCHIMP_CLIENT_ID`, `MAILCHIMP_CLIENT_SECRET`.
- Gotcha: no granular scopes (full account access). After token exchange, call the metadata endpoint to discover the user's datacenter (e.g. `us6`) before any API call will work.

### SendGrid 🔧
Send transactional/marketing email, manage templates.
- **Dashboard**: [app.sendgrid.com/settings/api_keys](https://app.sendgrid.com/settings/api_keys) → Create API Key → Restricted Access → grant only "Mail Send".
- Paste the key into the app's Connectors page (**not** `.env`).

### DocuSign 🔧
Create/send envelopes for e-signature, check status.
- **Dashboard**: free sandbox account at [developers.docusign.com](https://developers.docusign.com) → admindemo.docusign.com → Apps and Keys → Add App and Integration Key.
- Paste into `.env`: `DOCUSIGN_CLIENT_ID`, `DOCUSIGN_CLIENT_SECRET`.
- Gotcha: the registry points at the **sandbox** endpoints (`account-d.docusign.com`) — switch to `account.docusign.com` only after completing DocuSign's Go-Live promotion for real documents.

---

## Commerce & Finance

### Stripe 🔧
Read/manage customers, charges, invoices, subscriptions, refunds.
- **Dashboard**: [dashboard.stripe.com/apikeys](https://dashboard.stripe.com/apikeys) → Create restricted key → grant only the permissions needed.
- Paste the key into the app's Connectors page (**not** `.env`).
- Gotcha: use a restricted key (`rk_`), never the full secret key (`sk_`). Test (`_test_`) and live (`_live_`) keys are entirely separate data.

### PayPal 🔧
Read/manage orders, invoices, payouts, transactions.
- **Dashboard**: [developer.paypal.com/dashboard/applications](https://developer.paypal.com/dashboard/applications) → Sandbox or Live tab → Create App.
- Paste the Client ID, Client Secret, and whether it's sandbox or live into the app's Connectors page (**not** `.env`).
- Gotcha: PayPal's actual "Log in with PayPal" OAuth only grants identity info, not financial data — this client ID/secret pair is exchanged server-side instead.

### Shopify 🔧
Manage products, orders, customers, inventory.
- **Dashboard**: store admin → Settings → Apps and sales channels → Develop apps → Create an app → select Admin API scopes → Install app → reveal the Admin API access token.
- Paste the shop's `.myshopify.com` domain and the token into the app's Connectors page (**not** `.env`).
- Gotcha: as of 2026-01-01, new custom apps go through the Shopify Dev Dashboard with a 24h-expiring token instead of the old non-expiring one — verify current behavior for the specific store.

### QuickBooks (Intuit) 🔧
Read/manage invoices, bills, customers, reports.
- **Dashboard**: free account at [developer.intuit.com](https://developer.intuit.com) → Create an app (QuickBooks Online + Accounting API) → Keys & OAuth page.
- Paste into `.env`: `QUICKBOOKS_CLIENT_ID`, `QUICKBOOKS_CLIENT_SECRET`.
- Gotcha: refresh tokens are single-use and rotate on every refresh — the engine already handles saving the new one each time.

---

## Social Media

### Twitter/X 🔧
Read and post on your own account.
- **Dashboard**: [developer.x.com/en/portal/dashboard](https://developer.x.com/en/portal/dashboard) (requires a phone-verified account) → create a Project + App → enable OAuth 2.0 under User authentication settings.
- Paste into `.env`: `X_CLIENT_ID`, `X_CLIENT_SECRET`.
- Gotcha: X now requires paid API access even after OAuth succeeds (free tier for new developers closed Feb 2026) — confirm current pricing before relying on this.

### LinkedIn 🔧
Read your profile and, where approved, post on your behalf.
- **Dashboard**: reuses the app's existing [linkedin.com/developers/apps](https://www.linkedin.com/developers/apps) registration (already in `.env` as `LINKEDIN_CLIENT_ID`/`LINKEDIN_CLIENT_SECRET`) — just request the additional **"Share on LinkedIn"** product on that same app (self-serve `openid`/`profile`/`email` already work; posting needs this extra approval, which can take a few days).
- No new `.env` entries needed.
- Gotcha: LinkedIn doesn't issue long-lived refresh tokens to most apps — users will need to periodically re-authenticate (~60 days).

### Reddit 🔧
Read and post on your own account.
- **Dashboard**: [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) → create app → type "web app".
- Paste into `.env`: `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`.
- Gotcha: every API call needs a unique, descriptive `User-Agent` header or Reddit throttles it.

---

## Analytics

### Google Analytics 🔧
Read GA4 property traffic reports, funnels, custom dimensions/metrics.
- **Dashboard**: same Google Cloud project as Calendar/Gmail/Docs. Enable the "Google Analytics Data API".
- No new `.env` entries — reuses `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`.
- Gotcha: the connecting Google account needs at least Viewer access to the specific GA4 property; `analytics.readonly` is a sensitive scope with the same Testing-mode 7-day refresh token expiry as Gmail above until the app passes Google verification.
