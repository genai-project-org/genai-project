# Connector Setup Handbook

How the 52 connectors in `services/mcp/registry.py` get real credentials. The **env var table below is the source of truth**; the per-provider sections after the table are registration notes written earlier (their status emoji may lag the table).

## Three kinds of connector

**OAuth2** (default) - the user flips the toggle on the Connectors page, a popup opens to the provider's login/approve screen, and the popup closes itself. You register one OAuth app per provider once and put its Client ID / Secret in `apps/api/.env`; the same app serves every user. A connector is only switchable when both values are set (`/mcp/connectors` reports `configured`); otherwise its row shows a disabled toggle with a "Coming soon" tooltip. Zendesk and Shopify are per-account OAuth: the user is first asked for their subdomain / store domain.

**redirect_token** (Trello only) - no client secret and no code exchange; Trello returns the per-user token in the redirect. Only the public `TRELLO_API_KEY` is needed. Add every origin you serve the app from (e.g. `http://localhost:5174`, `https://iema.ai`) under "Allowed origins" for that key at trello.com/power-ups/admin.

**API key** (Telegram, Twilio, WhatsApp Business, Vercel, AWS, CircleCI, Freshdesk, SendGrid, PayPal) - the provider has no per-user consent flow, so the toggle opens a dialog where the user pastes a key. Nothing goes in `.env`; each user's value is stored encrypted per user. (Asana, Linear and Airtable are OAuth now, not API key.)

## Redirect URI

Register these exact redirect URIs at every OAuth provider (Trello: allowed origins instead):

- Local dev: `http://localhost:5174/connectors/oauth-callback`
- Production: `https://iema.ai/connectors/oauth-callback`

The web app always sends `<its own origin>/connectors/oauth-callback`, so one backend serves both. Optional `CONNECTOR_REDIRECT_URI` in `.env` pins it server-side (it then overrides what the browser sends for both the authorize and the token-exchange step). Do not use `APP_URL` for this: it is the API host. `NOTION_AUTHORIZATION_URL` in `.env` is unused; the authorize URL is built in code from `NOTION_CLIENT_ID` and the redirect URI above.

Quirks worth knowing before you test:
- Google: the redirect URI must be listed on the OAuth client, and the consent screen must list the Docs/Sheets/Drive/Analytics/cloud-platform scopes (or the account must be a test user).
- Atlassian: enable the Jira and Confluence scopes under Permissions, and add the callback URL under Authorization. One app serves both connectors.
- Microsoft: three Entra apps (`MS_GRAPH_*` for OneDrive/SharePoint/Azure, `MS_OUTLOOK_*`, `MS_TEAMS_*`). Each needs the Web redirect URI and the delegated permissions in the connector's scope list; Azure additionally needs "Azure Service Management / user_impersonation" on the Graph app.
- Dropbox, Zoom, GitLab, monday and Asana: scopes are taken from the app configuration. Dropbox/Zoom/monday/Asana send no `scope`; GitLab sends `api read_user`. To change scopes without code, set `<CONNECTOR_ID>_SCOPES` (space or comma separated), e.g. `GITLAB_SCOPES=read_api read_user`.
- Airtable requires PKCE (implemented) and Basic client auth (implemented); Salesforce external client apps also expect PKCE (sent).
- Salesforce authorizes against `login.salesforce.com` (production/developer orgs); sandboxes need `test.salesforce.com`.
- LinkedIn uses its own `LINKEDIN_MCP_CLIENT_ID/SECRET`, separate from the sign-in app's `LINKEDIN_CLIENT_ID/SECRET`.

## Status at launch

Credentials present: Asana, Atlassian (Jira + Confluence), GitHub, Google (Calendar, Gmail, Docs, Sheets, Drive, GCP, Analytics), Intercom, Linear, monday, Notion, Sentry, Slack, Airtable, Basecamp, Bitbucket, Discord, Dropbox, GitLab, Microsoft (OneDrive, SharePoint, Azure, Outlook, Teams), Salesforce, Trello, Zendesk, Zoom, plus the nine API-key connectors.

Coming soon (no credentials yet): HubSpot, DocuSign, LinkedIn, Mailchimp, QuickBooks, Reddit, Shopify, Stripe, X, Box, ClickUp. Fill the vars below, restart the API, and the toggle works with no code change.

How @mention / prompts reach each connector (`Tool access` column): **Own tool server** (`services/mcp/servers/*`: Gmail, Calendar, Slack, GitHub, Notion, Linear, Asana, Airtable, Trello), **Hosted MCP** (monday, Intercom, HubSpot, called with the user's OAuth token as a bearer; not verified end to end), **Generic REST tools** (`servers/rest_server.py`: `api_get/api_post/api_put/api_patch/api_delete` locked to the provider's API hosts, token never sent elsewhere, deletes need user confirmation; used for Google Docs/Sheets/Drive/GCP/Analytics, Microsoft, Atlassian, Sentry, Dropbox, GitLab, Bitbucket, Zoom, Basecamp, Zendesk, Salesforce, Discord). Connectors listed as "No tool server" can be connected but the assistant reports that actions are not available yet. Discord has only a user token (profile and server list); message actions would need a bot token.

Set `MCP_DEMO_MODE=1` to hide raw provider error text in the Workspace timeline.

## Env var reference (all connectors)

Google connectors share `GOOGLE_CLIENT_ID/SECRET`; OneDrive, SharePoint and Azure share `MS_GRAPH_CLIENT_ID/SECRET`; Jira and Confluence share `ATLASSIAN_CLIENT_ID/SECRET`.

| Connector | Category | Auth | Tool access | Env vars in `apps/api/.env` |
|---|---|---|---|---|
| Google Analytics | Analytics | OAuth2 | Generic REST tools | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` |
| DocuSign | CRM & Support | OAuth2 | No tool server | `DOCUSIGN_CLIENT_ID`, `DOCUSIGN_CLIENT_SECRET` |
| Freshdesk | CRM & Support | API key | No tool server | _none — each user pastes: `api_key`, `domain`_ |
| HubSpot | CRM & Support | OAuth2 | Hosted MCP | `HUBSPOT_CLIENT_ID`, `HUBSPOT_CLIENT_SECRET` |
| Intercom | CRM & Support | OAuth2 | Hosted MCP | `INTERCOM_CLIENT_ID`, `INTERCOM_CLIENT_SECRET` |
| Mailchimp | CRM & Support | OAuth2 | No tool server | `MAILCHIMP_CLIENT_ID`, `MAILCHIMP_CLIENT_SECRET` |
| Salesforce | CRM & Support | OAuth2 | Generic REST tools | `SALESFORCE_CLIENT_ID`, `SALESFORCE_CLIENT_SECRET` |
| SendGrid | CRM & Support | API key | No tool server | _none — each user pastes: `api_key`_ |
| Zendesk | CRM & Support | OAuth2 | Generic REST tools | `ZENDESK_CLIENT_ID`, `ZENDESK_CLIENT_SECRET` |
| Google Calendar | Calendar & Scheduling | OAuth2 | Own tool server | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` |
| PayPal | Commerce & Finance | API key | No tool server | _none — each user pastes: `client_id`, `client_secret`, `mode`_ |
| QuickBooks (Intuit) | Commerce & Finance | OAuth2 | No tool server | `QUICKBOOKS_CLIENT_ID`, `QUICKBOOKS_CLIENT_SECRET` |
| Shopify | Commerce & Finance | OAuth2 | No tool server | `SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET` |
| Stripe | Commerce & Finance | OAuth2 | No tool server | `STRIPE_CONNECT_CLIENT_ID`, `STRIPE_CONNECT_CLIENT_SECRET` |
| Discord | Communication | OAuth2 | Generic REST tools | `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET` |
| Gmail | Communication | OAuth2 | Own tool server | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` |
| Microsoft Outlook (Mail) | Communication | OAuth2 | Generic REST tools | `MS_OUTLOOK_CLIENT_ID`, `MS_OUTLOOK_CLIENT_SECRET` |
| Microsoft Teams | Communication | OAuth2 | Generic REST tools | `MS_TEAMS_CLIENT_ID`, `MS_TEAMS_CLIENT_SECRET` |
| Slack | Communication | OAuth2 | Own tool server | `SLACK_CLIENT_ID`, `SLACK_CLIENT_SECRET` |
| Telegram | Communication | API key | No tool server | _none — each user pastes: `bot_token`_ |
| Twilio | Communication | API key | No tool server | _none — each user pastes: `account_sid`, `api_key_sid`, `api_key_secret`_ |
| WhatsApp Business | Communication | API key | No tool server | _none — each user pastes: `system_user_access_token`, `phone_number_id`, `whatsapp_business_account_id`_ |
| Zoom | Communication | OAuth2 | Generic REST tools | `ZOOM_CLIENT_ID`, `ZOOM_CLIENT_SECRET` |
| Amazon Web Services | Developer Tools | API key | No tool server | _none — each user pastes: `access_key_id`, `secret_access_key`, `region`_ |
| Bitbucket | Developer Tools | OAuth2 | Generic REST tools | `BITBUCKET_CLIENT_ID`, `BITBUCKET_CLIENT_SECRET` |
| CircleCI | Developer Tools | API key | No tool server | _none — each user pastes: `api_token`_ |
| GitHub | Developer Tools | OAuth2 | Own tool server | `GITHUB_MCP_CLIENT_ID`, `GITHUB_MCP_CLIENT_SECRET` |
| GitLab | Developer Tools | OAuth2 | Generic REST tools | `GITLAB_CLIENT_ID`, `GITLAB_CLIENT_SECRET` |
| Google Cloud Platform | Developer Tools | OAuth2 | Generic REST tools | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` |
| Microsoft Azure | Developer Tools | OAuth2 | Generic REST tools | `MS_GRAPH_CLIENT_ID`, `MS_GRAPH_CLIENT_SECRET` |
| Sentry | Developer Tools | OAuth2 | Generic REST tools | `SENTRY_CLIENT_ID`, `SENTRY_CLIENT_SECRET` |
| Vercel | Developer Tools | API key | No tool server | _none — each user pastes: `access_token`_ |
| Atlassian Confluence | Productivity & Docs | OAuth2 | Generic REST tools | `ATLASSIAN_CLIENT_ID`, `ATLASSIAN_CLIENT_SECRET` |
| Box | Productivity & Docs | OAuth2 | No tool server | `BOX_CLIENT_ID`, `BOX_CLIENT_SECRET` |
| Dropbox | Productivity & Docs | OAuth2 | Generic REST tools | `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET` |
| Google Docs | Productivity & Docs | OAuth2 | Generic REST tools | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` |
| Google Drive | Productivity & Docs | OAuth2 | Generic REST tools | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` |
| Google Sheets | Productivity & Docs | OAuth2 | Generic REST tools | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` |
| Microsoft OneDrive | Productivity & Docs | OAuth2 | Generic REST tools | `MS_GRAPH_CLIENT_ID`, `MS_GRAPH_CLIENT_SECRET` |
| Microsoft SharePoint | Productivity & Docs | OAuth2 | Generic REST tools | `MS_GRAPH_CLIENT_ID`, `MS_GRAPH_CLIENT_SECRET` |
| Notion | Productivity & Docs | OAuth2 | Own tool server | `NOTION_CLIENT_ID`, `NOTION_CLIENT_SECRET` |
| Airtable | Project Management | OAuth2 | Own tool server | `AIRTABLE_CLIENT_ID`, `AIRTABLE_CLIENT_SECRET` |
| Asana | Project Management | OAuth2 | Own tool server | `ASANA_CLIENT_ID`, `ASANA_CLIENT_SECRET` |
| Atlassian Jira | Project Management | OAuth2 | Generic REST tools | `ATLASSIAN_CLIENT_ID`, `ATLASSIAN_CLIENT_SECRET` |
| Basecamp | Project Management | OAuth2 | Generic REST tools | `BASECAMP_CLIENT_ID`, `BASECAMP_CLIENT_SECRET` |
| ClickUp | Project Management | OAuth2 | No tool server | `CLICKUP_CLIENT_ID`, `CLICKUP_CLIENT_SECRET` |
| Linear | Project Management | OAuth2 | Own tool server | `LINEAR_CLIENT_ID`, `LINEAR_CLIENT_SECRET` |
| Trello | Project Management | Redirect token | Own tool server | `TRELLO_API_KEY` (public key, no secret) |
| monday.com | Project Management | OAuth2 | Hosted MCP | `MONDAY_CLIENT_ID`, `MONDAY_CLIENT_SECRET` |
| LinkedIn | Social Media | OAuth2 | No tool server | `LINKEDIN_MCP_CLIENT_ID`, `LINKEDIN_MCP_CLIENT_SECRET` |
| Reddit | Social Media | OAuth2 | No tool server | `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` |
| Twitter/X | Social Media | OAuth2 | No tool server | `X_CLIENT_ID`, `X_CLIENT_SECRET` |

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

### Slack ✅ Ready
List channels, read history, post messages.
- **Dashboard**: [api.slack.com/apps](https://api.slack.com/apps) → Create New App. Under OAuth & Permissions add the redirect URI above and bot scopes `channels:read`, `chat:write`, `channels:history`. Slack requires an HTTPS redirect for non-localhost installs.
- Paste into `.env`: `SLACK_CLIENT_ID`, `SLACK_CLIENT_SECRET`.
- The bot must be invited to a channel (`/invite @app`) before it can read or post there.

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

### Notion ✅ Ready
Search, read, create and append to pages.
- **Dashboard**: [notion.so/profile/integrations](https://www.notion.so/profile/integrations) → New integration, type **Public**. Redirect URI = the one above.
- Paste into `.env`: `NOTION_CLIENT_ID`, `NOTION_CLIENT_SECRET`. The token endpoint uses HTTP Basic auth and a JSON body; both are handled by `token_basic_auth` / `token_request_json` in the registry.
- Only pages the user shares with the integration on the consent screen are visible to the assistant.
- Tool server: `services/mcp/servers/notion_server.py`.

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
Read/manage tasks and projects.
- **OAuth2**: create the app at [app.asana.com/0/my-apps](https://app.asana.com/0/my-apps), set `ASANA_CLIENT_ID/SECRET`. Authorize `https://app.asana.com/-/oauth_authorize`, token `https://app.asana.com/-/oauth_token`.
- Tool server: `services/mcp/servers/asana_server.py`.

### Linear ✅ Ready
Read/manage issues and comments.
- **OAuth2**: app at [linear.app/settings/api](https://linear.app/settings/api), set `LINEAR_CLIENT_ID/SECRET`. Scopes `read,write` (comma separated). Token is sent as a Bearer token.
- Tool server: `services/mcp/servers/linear_server.py` (GraphQL).

### Trello ✅ Ready
Read/manage boards, lists, and cards.
- **Dashboard** (one-time, operator-only): [trello.com/power-ups/admin](https://trello.com/power-ups/admin) → create a Power-Up, open its API Key tab, generate a key.
- Paste into `.env`: `TRELLO_API_KEY` (public identifier, safe in the authorize URL). The user just clicks Connect and approves in the popup.
- Tool server: `services/mcp/servers/trello_server.py`.

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

### Airtable ✅ Ready
Read/manage bases, tables, records.
- **OAuth2** with PKCE + Basic client auth (both implemented): set `AIRTABLE_CLIENT_ID/SECRET`, enable scopes `data.records:read`, `data.records:write`, `schema.bases:read` on the integration.
- Tool server: `services/mcp/servers/airtable_server.py`.

---

## Developer Tools

### GitHub ✅ Ready
List repos/issues/PRs, create issues, comment, search code.
- **Dashboard**: [github.com/settings/developers](https://github.com/settings/developers) → New OAuth App (separate from the app's own login OAuth app). Callback URL = the redirect URI above.
- Paste into `.env`: `GITHUB_MCP_CLIENT_ID`, `GITHUB_MCP_CLIENT_SECRET`.
- Tool server: `services/mcp/servers/github_server.py` (REST, uses the user's OAuth token).

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
Call Azure Resource Manager APIs on resources you have permission to manage.
- Real delegated OAuth — the user just logs in with their own Microsoft account and approves; they can only ever act on resources that account already has permission on. No service principal or client secret from them.
- **Dashboard** (operator, one-time): reuse the same Entra app registration as Microsoft Teams/Outlook/OneDrive above. Under API permissions, add **Azure Service Management** (delegated, `user_impersonation`) alongside whatever Graph permissions it already has.
- No new `.env` entries — reuses `MS_GRAPH_CLIENT_ID`/`MS_GRAPH_CLIENT_SECRET`.

### GCP 🔧
Call GCP APIs (Cloud SQL, BigQuery, Storage, etc.) on your own projects.
- Real OAuth — same Google account consent screen as Calendar/Gmail/Docs, just the broader `cloud-platform` scope. The user grants delegated access to their own GCP projects; no service account JSON key needed from them.
- **Dashboard**: same Google Cloud project as Calendar/Gmail — no new app registration needed.
- No new `.env` entries — reuses `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`.
- Gotcha: `cloud-platform` is a broad/sensitive scope — the same Testing-mode 100-user cap and Google verification requirement as the other Google connectors applies past that.

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
- Real OAuth2 — Stripe Connect, Stripe's own recommended pattern for "let a third-party app manage a user's Stripe account on their behalf." The user clicks Connect, logs into Stripe, approves — no key typed.
- **Dashboard** (operator, one-time): Stripe Dashboard → Settings → Connect → enable Connect → copy the platform Client ID (`ca_...`).
- Paste into `.env`: `STRIPE_CONNECT_CLIENT_ID`, `STRIPE_CONNECT_CLIENT_SECRET`.
- Gotcha: test and live modes use separate Connect client IDs, same as Stripe's regular API keys.

### PayPal 🔧
Read/manage orders, invoices, payouts, transactions.
- **Dashboard**: [developer.paypal.com/dashboard/applications](https://developer.paypal.com/dashboard/applications) → Sandbox or Live tab → Create App.
- Paste the Client ID, Client Secret, and whether it's sandbox or live into the app's Connectors page (**not** `.env`).
- Gotcha: PayPal's actual "Log in with PayPal" OAuth only grants identity info, not financial data — this client ID/secret pair is exchanged server-side instead.

### Shopify 🔧
Manage products, orders, customers, inventory.
- Real OAuth2, but per-store — every shop has its own authorize/token host. The Connectors page asks the user for their store domain (not a secret) right before opening the popup.
- **Dashboard** (operator, one-time): [partners.shopify.com](https://partners.shopify.com) → create a Public (or Custom Distribution) app → set the redirect URI → copy the Client ID/Secret. One app works across every store that installs it.
- Paste into `.env`: `SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET`.
- Gotcha: as of 2026-01-01, new apps get a 24h-expiring access token instead of the old non-expiring one — `oauth_service.py`'s generic refresh path only engages if Shopify's token response includes `expires_in`; verify current behavior for the specific store before relying on long-lived access.

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
