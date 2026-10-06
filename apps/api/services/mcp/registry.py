"""Connector registry — the pluggable pattern for the MCP engine.

Adding service #5 means adding one ConnectorConfig entry here (plus, if the
provider has no hosted remote MCP server, a small stdio server module under
services/mcp/servers/) — never new routes, new OAuth plumbing, or new
tool-loop code. Everything else (services/mcp/oauth_service.py,
client_host.py, orchestrator_service.py, routers/mcp_routes.py) is generic
over this config.
"""
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# apps/api root — used as the cwd when spawning our own stdio connector
# servers, so `python -m services.mcp.servers.X` resolves as a package
# regardless of the FastAPI process's own working directory.
API_ROOT_DIR = Path(__file__).resolve().parent.parent.parent


@dataclass(frozen=True)
class ConnectorConfig:
    id: str
    display_name: str
    description: str
    category: str = "Other"  # groups the frontend's connector list
    scopes: List[str] = field(default_factory=list)

    # auth_type picks which half of the engine handles this connector:
    #
    # "oauth2" — a real 3-legged, user-consent browser redirect. Needs a
    #   server-wide OAuth app (client_id_env/client_secret_env below) that
    #   *you* register once in the provider's dev dashboard; each user then
    #   clicks "Connect" and approves it for their own account.
    #   (routers/mcp_routes.py's /connect + /callback, services/mcp/oauth_service.py)
    #
    # "api_key" — the provider has no practical per-user consent redirect
    #   for this use case (a static secret key/token/PAT the user copies
    #   from their own dashboard instead — e.g. a Stripe secret key, AWS
    #   access keys, a Twilio Account SID + Auth Token). No server-wide app
    #   registration needed; `credential_fields` lists what to collect from
    #   the user, `credential_env_map` says which env var each one is
    #   injected under when spawning that connector's stdio server.
    #   (routers/mcp_routes.py's /connections/{id}/api-key, services/mcp/api_key_service.py)
    auth_type: str = "oauth2"

    # ---- oauth2 fields ----
    # OAuth endpoints + credentials (the actual secret values live in env
    # vars, never hardcoded — see client_id_env/client_secret_env).
    authorize_url: Optional[str] = None
    token_url: Optional[str] = None
    client_id_env: Optional[str] = None
    client_secret_env: Optional[str] = None
    extra_authorize_params: Dict[str, str] = field(default_factory=dict)
    # stdio only: the single decrypted access token is injected under this
    # env var name (never as a CLI argument — that would leak into `ps`).
    token_env_var: Optional[str] = None

    # ---- api_key fields ----
    credential_fields: List[str] = field(default_factory=list)
    credential_env_map: Dict[str, str] = field(default_factory=dict)

    # Transport: exactly one of the two blocks below is used, per `transport`.
    transport: str = "stdio"  # "stdio" | "http"

    # stdio: we spawn `stdio_command` with `stdio_args`.
    stdio_command: Optional[str] = None
    stdio_args: List[str] = field(default_factory=list)

    # http: a hosted remote MCP server (Streamable HTTP), authenticated via
    # a plain `Authorization: Bearer <token>` header. oauth2-only in this
    # engine — an api_key connector needing HTTP transport should wrap the
    # provider's REST API in its own stdio server instead (same reasoning as
    # the hand-rolled Calendar/Slack servers), so its raw credentials never
    # need to double as a bearer token.
    http_url: Optional[str] = None

    # "ready" — the transport above is actually wired to a real, tested tool
    #   server (one of ours, or a verified npm/pip package with a documented
    #   env-var contract) and a Connect + prompt will really call real tools.
    # "needs_server" — Connect/disconnect and credential storage work today
    #   (so registering the OAuth app or pasting the API key now is NOT
    #   wasted), but no tool server is wired up yet; client_host refuses to
    #   spawn anything and orchestrator_service reports this plainly instead
    #   of a confusing crash. `mcp_notes` names what to build/verify next —
    #   see CONNECTOR_SETUP.md for the researched starting point per service.
    mcp_status: str = "ready"
    mcp_notes: str = ""

    def client_id(self) -> str:
        return os.environ.get(self.client_id_env, "") if self.client_id_env else ""

    def client_secret(self) -> str:
        return os.environ.get(self.client_secret_env, "") if self.client_secret_env else ""

    def is_configured(self) -> bool:
        """Whether this server is ready to offer the connector at all.

        oauth2: the server-wide app credentials must be set. api_key: always
        true — there's nothing to configure server-side, each user supplies
        their own key(s) directly.
        """
        if self.auth_type == "api_key":
            return True
        return bool(self.client_id() and self.client_secret())


CONNECTORS: Dict[str, ConnectorConfig] = {
    "google_calendar": ConnectorConfig(
        id="google_calendar",
        display_name="Google Calendar",
        description="Read and manage events on your Google Calendar.",
        category="Calendar & Scheduling",
        scopes=["https://www.googleapis.com/auth/calendar"],
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        client_id_env="GOOGLE_CLIENT_ID",
        client_secret_env="GOOGLE_CLIENT_SECRET",
        # access_type=offline + prompt=consent mirrors gmail_service.py — the
        # only way Google issues a refresh_token.
        extra_authorize_params={"access_type": "offline", "prompt": "consent"},
        transport="stdio",
        stdio_command=sys.executable,
        stdio_args=["-m", "services.mcp.servers.google_calendar_server"],
        token_env_var="GOOGLE_CALENDAR_ACCESS_TOKEN",
    ),
    "github": ConnectorConfig(
        id="github",
        display_name="GitHub",
        description="Create issues/PRs, search code, and manage repos on your behalf.",
        category="Developer Tools",
        scopes=["repo", "read:user"],
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        # NOTE: a separate OAuth App from auth_routes.py's login flow — that
        # one only ever requests profile info. Register a new OAuth App at
        # github.com/settings/developers and set these two env vars.
        client_id_env="GITHUB_MCP_CLIENT_ID",
        client_secret_env="GITHUB_MCP_CLIENT_SECRET",
        transport="http",
        # Official hosted remote MCP server — verify this URL is still
        # current in GitHub's MCP docs before relying on it.
        http_url="https://api.githubcopilot.com/mcp/",
    ),
    "slack": ConnectorConfig(
        id="slack",
        display_name="Slack",
        description="Read channels and post messages in your Slack workspace.",
        category="Communication",
        scopes=["channels:read", "chat:write", "channels:history"],
        authorize_url="https://slack.com/oauth/v2/authorize",
        token_url="https://slack.com/api/oauth.v2.access",
        client_id_env="SLACK_CLIENT_ID",
        client_secret_env="SLACK_CLIENT_SECRET",
        transport="stdio",
        stdio_command=sys.executable,
        stdio_args=["-m", "services.mcp.servers.slack_server"],
        token_env_var="SLACK_BOT_TOKEN",
    ),
    "notion": ConnectorConfig(
        id="notion",
        display_name="Notion",
        description="Search, read, and edit pages in your Notion workspace.",
        category="Productivity & Docs",
        scopes=[],
        # Notion's remote-MCP OAuth flow needs to be re-verified against
        # their current docs (it may use OAuth 2.1 dynamic client
        # registration instead of a manually-issued client id/secret) —
        # these placeholders should be confirmed/updated when this
        # connector is actually wired up and tested.
        authorize_url="https://api.notion.com/v1/oauth/authorize",
        token_url="https://api.notion.com/v1/oauth/token",
        client_id_env="NOTION_CLIENT_ID",
        client_secret_env="NOTION_CLIENT_SECRET",
        transport="http",
        http_url="https://mcp.notion.com/mcp",
    ),

    # ============== Communication ==============
    "gmail": ConnectorConfig(
        id="gmail", display_name="Gmail", category="Communication",
        description="Read and send email through your Gmail account.",
        scopes=["https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.send"],
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        client_id_env="GOOGLE_CLIENT_ID", client_secret_env="GOOGLE_CLIENT_SECRET",
        extra_authorize_params={"access_type": "offline", "prompt": "consent"},
        transport="stdio", stdio_command=sys.executable,
        stdio_args=["-m", "services.mcp.servers.gmail_server"], token_env_var="GMAIL_ACCESS_TOKEN",
    ),
    "microsoft_teams": ConnectorConfig(
        id="microsoft_teams", display_name="Microsoft Teams", category="Communication",
        description="Read and post messages in your Teams chats and channels.",
        scopes=["offline_access", "User.Read", "Team.ReadBasic.All", "Channel.ReadBasic.All", "ChannelMessage.Send", "Chat.ReadWrite"],
        authorize_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        client_id_env="MS_TEAMS_CLIENT_ID", client_secret_env="MS_TEAMS_CLIENT_SECRET",
        mcp_status="needs_server",
        mcp_notes="No official Microsoft MCP server. Candidates to build from: PyPI `mcp-teams-server` or npm `@floriscornel/teams-mcp` (both community, wrap Microsoft Graph).",
    ),
    "discord": ConnectorConfig(
        id="discord", display_name="Discord", category="Communication",
        description="Send and read messages in Discord servers you install the bot into.",
        scopes=["identify", "guilds", "bot"],
        authorize_url="https://discord.com/oauth2/authorize", token_url="https://discord.com/api/oauth2/token",
        client_id_env="DISCORD_CLIENT_ID", client_secret_env="DISCORD_CLIENT_SECRET",
        mcp_status="needs_server",
        mcp_notes=("Hybrid auth: the OAuth flow only lets a user pick which server to install the bot into — actual "
                   "message send/read uses one static platform-wide Bot Token (from the Discord Developer Portal's "
                   "Bot tab), not a per-user token. Community packages: npm `@barryyip0625/mcp-discord` or `@IQAIcom/mcp-discord`."),
    ),
    "zoom": ConnectorConfig(
        id="zoom", display_name="Zoom", category="Communication",
        description="Create and manage Zoom meetings on your behalf.",
        scopes=["user:read:user", "meeting:write:meeting", "meeting:read:meeting"],
        authorize_url="https://zoom.us/oauth/authorize", token_url="https://zoom.us/oauth/token",
        client_id_env="ZOOM_CLIENT_ID", client_secret_env="ZOOM_CLIENT_SECRET",
        mcp_status="needs_server",
        mcp_notes="No single trustworthy community/official MCP package found — build a thin stdio wrapper over Zoom's REST API (same shape as servers/google_calendar_server.py).",
    ),
    "microsoft_outlook_mail": ConnectorConfig(
        id="microsoft_outlook_mail", display_name="Microsoft Outlook (Mail)", category="Communication",
        description="Read and send email through your Outlook/Microsoft 365 mailbox.",
        scopes=["offline_access", "User.Read", "Mail.Read", "Mail.Send"],
        authorize_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        client_id_env="MS_OUTLOOK_CLIENT_ID", client_secret_env="MS_OUTLOOK_CLIENT_SECRET",
        mcp_status="needs_server",
        mcp_notes="No well-established MCP package found — build a thin stdio wrapper over Microsoft Graph's /me/messages endpoints (same shape as servers/gmail_server.py). Can reuse the same Entra app registration as Teams/OneDrive/SharePoint.",
    ),
    "telegram": ConnectorConfig(
        id="telegram", display_name="Telegram", category="Communication",
        description="Send and receive messages as a Telegram bot you add to chats/groups.",
        auth_type="api_key", credential_fields=["bot_token"], credential_env_map={"bot_token": "TELEGRAM_BOT_TOKEN"},
        mcp_status="needs_server",
        mcp_notes=("No credentials-only registration needed — the token comes from @BotFather inside Telegram, not a web dashboard. "
                   "Build a thin stdio wrapper over the Bot API (api.telegram.org/bot<token>/...); avoid 'telegram-mcp' packages that "
                   "wrap the MTProto *user* API instead of the Bot API."),
    ),
    "twilio": ConnectorConfig(
        id="twilio", display_name="Twilio", category="Communication",
        description="Send SMS/WhatsApp messages and manage calls through your Twilio account.",
        auth_type="api_key", credential_fields=["account_sid", "api_key_sid", "api_key_secret"],
        credential_env_map={"account_sid": "TWILIO_ACCOUNT_SID", "api_key_sid": "TWILIO_API_KEY_SID", "api_key_secret": "TWILIO_API_KEY_SECRET"},
        transport="stdio", stdio_command="npx",
        stdio_args=["-y", "@twilio-alpha/mcp"],
        mcp_status="needs_server",
        mcp_notes=("Official `@twilio-alpha/mcp` (npm, Alpha quality) exists but takes credentials as a CLI positional arg "
                   "(`ACCOUNT_SID/API_KEY:API_SECRET`), not plain env vars — needs a small wrapper script to build that arg "
                   "from credential_env_map before this can be marked ready."),
    ),
    "whatsapp_business": ConnectorConfig(
        id="whatsapp_business", display_name="WhatsApp Business", category="Communication",
        description="Send and receive WhatsApp Business messages via Meta's Cloud API.",
        auth_type="api_key", credential_fields=["system_user_access_token", "phone_number_id", "whatsapp_business_account_id"],
        credential_env_map={"system_user_access_token": "WHATSAPP_ACCESS_TOKEN", "phone_number_id": "WHATSAPP_PHONE_NUMBER_ID", "whatsapp_business_account_id": "WHATSAPP_BUSINESS_ACCOUNT_ID"},
        mcp_status="needs_server",
        mcp_notes="No trustworthy official or community MCP server found — build a thin stdio wrapper over the Graph API's /messages endpoint.",
    ),

    # ============== Productivity & Docs ==============
    "google_docs": ConnectorConfig(
        id="google_docs", display_name="Google Docs", category="Productivity & Docs",
        description="Read, create, and edit your Google Docs documents.",
        scopes=["https://www.googleapis.com/auth/documents", "https://www.googleapis.com/auth/drive.file"],
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth", token_url="https://oauth2.googleapis.com/token",
        client_id_env="GOOGLE_CLIENT_ID", client_secret_env="GOOGLE_CLIENT_SECRET",
        extra_authorize_params={"access_type": "offline", "prompt": "consent"},
        mcp_status="needs_server",
        mcp_notes="Community/archived npm `@modelcontextprotocol/server-gdrive` is read-mostly; build a small stdio wrapper over the Docs API for real create/edit tools.",
    ),
    "google_sheets": ConnectorConfig(
        id="google_sheets", display_name="Google Sheets", category="Productivity & Docs",
        description="Read, create, and edit your Google Sheets spreadsheets.",
        scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive.file"],
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth", token_url="https://oauth2.googleapis.com/token",
        client_id_env="GOOGLE_CLIENT_ID", client_secret_env="GOOGLE_CLIENT_SECRET",
        extra_authorize_params={"access_type": "offline", "prompt": "consent"},
        mcp_status="needs_server",
        mcp_notes="No dedicated official Sheets MCP — build a small stdio wrapper over the Sheets API's values.get/update.",
    ),
    "google_drive": ConnectorConfig(
        id="google_drive", display_name="Google Drive", category="Productivity & Docs",
        description="Search, list, read, and upload files in your Google Drive.",
        scopes=["https://www.googleapis.com/auth/drive.file"],
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth", token_url="https://oauth2.googleapis.com/token",
        client_id_env="GOOGLE_CLIENT_ID", client_secret_env="GOOGLE_CLIENT_SECRET",
        extra_authorize_params={"access_type": "offline", "prompt": "consent"},
        mcp_status="needs_server",
        mcp_notes="Community/archived npm `@modelcontextprotocol/server-gdrive` — treat as a starting point only, verify before depending on it.",
    ),
    "atlassian_confluence": ConnectorConfig(
        id="atlassian_confluence", display_name="Atlassian Confluence", category="Productivity & Docs",
        description="Search, read, and create/edit pages in your Confluence spaces.",
        scopes=["read:confluence-content.all", "read:confluence-space.summary", "write:confluence-content", "offline_access"],
        authorize_url="https://auth.atlassian.com/authorize", token_url="https://auth.atlassian.com/oauth/token",
        client_id_env="ATLASSIAN_CLIENT_ID", client_secret_env="ATLASSIAN_CLIENT_SECRET",
        extra_authorize_params={"audience": "api.atlassian.com", "prompt": "consent"},
        transport="http", http_url="https://mcp.atlassian.com/v1/mcp/authv2",
        mcp_notes="Official hosted remote MCP (Rovo, Cloud-only), shared with the atlassian_jira connector below — same OAuth app.",
    ),
    "microsoft_onedrive": ConnectorConfig(
        id="microsoft_onedrive", display_name="Microsoft OneDrive", category="Productivity & Docs",
        description="List, read, upload, and manage files in your OneDrive.",
        scopes=["Files.ReadWrite", "offline_access", "User.Read"],
        authorize_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        client_id_env="MS_GRAPH_CLIENT_ID", client_secret_env="MS_GRAPH_CLIENT_SECRET",
        mcp_status="needs_server",
        mcp_notes="Community npm `ms-365-mcp-server` wraps Graph incl. OneDrive; verify its OAuth/env-var contract before depending on it.",
    ),
    "microsoft_sharepoint": ConnectorConfig(
        id="microsoft_sharepoint", display_name="Microsoft SharePoint", category="Productivity & Docs",
        description="Read and edit documents/lists in your SharePoint Online sites.",
        scopes=["Sites.ReadWrite.All", "offline_access", "User.Read"],
        authorize_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        client_id_env="MS_GRAPH_CLIENT_ID", client_secret_env="MS_GRAPH_CLIENT_SECRET",
        mcp_status="needs_server",
        mcp_notes=("Reuses the same Entra app registration as OneDrive. Sites.ReadWrite.All may require an org admin "
                   "to grant consent — not self-serve in every tenant. Community npm `ms-365-mcp-server` as a starting point."),
    ),
    "dropbox": ConnectorConfig(
        id="dropbox", display_name="Dropbox", category="Productivity & Docs",
        description="List, read, upload, and manage files in your Dropbox.",
        scopes=["files.content.read", "files.content.write", "files.metadata.read", "files.metadata.write"],
        authorize_url="https://www.dropbox.com/oauth2/authorize", token_url="https://api.dropbox.com/oauth2/token",
        client_id_env="DROPBOX_APP_KEY", client_secret_env="DROPBOX_APP_SECRET",
        extra_authorize_params={"token_access_type": "offline"},
        mcp_status="needs_server",
        mcp_notes="Community npm `dbx-mcp-server` (unaffiliated with Dropbox) as a starting point — or build a thin wrapper, same shape as servers/google_calendar_server.py.",
    ),
    "box": ConnectorConfig(
        id="box", display_name="Box", category="Productivity & Docs",
        description="List, read, upload, and manage files/folders in your Box account.",
        scopes=["root_readwrite"],
        authorize_url="https://account.box.com/api/oauth2/authorize", token_url="https://api.box.com/oauth2/token",
        client_id_env="BOX_CLIENT_ID", client_secret_env="BOX_CLIENT_SECRET",
        mcp_status="needs_server",
        mcp_notes="Box runs an official hosted MCP (mcp.box.com) but it's admin/enterprise-gated, not self-serve for an individual account — build a thin stdio wrapper over Box's REST API using this OAuth app instead.",
    ),

    # ============== Project Management ==============
    "asana": ConnectorConfig(
        id="asana", display_name="Asana", category="Project Management",
        description="Read and manage your Asana tasks, projects, and comments.",
        scopes=["tasks:read", "tasks:write", "projects:read", "projects:write", "users:read"],
        authorize_url="https://app.asana.com/-/oauth_authorize", token_url="https://app.asana.com/-/oauth_token",
        client_id_env="ASANA_CLIENT_ID", client_secret_env="ASANA_CLIENT_SECRET",
        transport="http", http_url="https://mcp.asana.com/v2/mcp",
    ),
    "linear": ConnectorConfig(
        id="linear", display_name="Linear", category="Project Management",
        description="Read and manage your Linear issues, projects, cycles, and comments.",
        scopes=["read", "write", "issues:create", "comments:create"],
        authorize_url="https://linear.app/oauth/authorize", token_url="https://api.linear.app/oauth/token",
        client_id_env="LINEAR_CLIENT_ID", client_secret_env="LINEAR_CLIENT_SECRET",
        transport="http", http_url="https://mcp.linear.app/mcp",
    ),
    "atlassian_jira": ConnectorConfig(
        id="atlassian_jira", display_name="Atlassian Jira", category="Project Management",
        description="Read and manage your Jira Cloud issues, projects, and comments.",
        scopes=["read:jira-work", "write:jira-work", "read:jira-user", "offline_access"],
        authorize_url="https://auth.atlassian.com/authorize", token_url="https://auth.atlassian.com/oauth/token",
        client_id_env="ATLASSIAN_CLIENT_ID", client_secret_env="ATLASSIAN_CLIENT_SECRET",
        extra_authorize_params={"audience": "api.atlassian.com", "prompt": "consent"},
        transport="http", http_url="https://mcp.atlassian.com/v1/mcp/authv2",
        mcp_notes="Official hosted remote MCP (Rovo, Cloud-only), shared with the atlassian_confluence connector — same OAuth app.",
    ),
    "trello": ConnectorConfig(
        id="trello", display_name="Trello", category="Project Management",
        description="Read and manage your Trello boards, lists, and cards.",
        auth_type="api_key", credential_fields=["api_key", "token"],
        credential_env_map={"api_key": "TRELLO_API_KEY", "token": "TRELLO_TOKEN"},
        mcp_status="needs_server",
        mcp_notes=("Trello has no real OAuth2 token endpoint — it's an API-key + a per-user token obtained via a "
                   "simplified redirect+fragment flow (see CONNECTOR_SETUP.md). Community npm packages exist "
                   "(e.g. trello-mcp-server) but maintenance is unverified."),
    ),
    "clickup": ConnectorConfig(
        id="clickup", display_name="ClickUp", category="Project Management",
        description="Read and manage your ClickUp tasks, lists, and docs.",
        scopes=[],
        authorize_url="https://app.clickup.com/api", token_url="https://api.clickup.com/api/v2/oauth/token",
        client_id_env="CLICKUP_CLIENT_ID", client_secret_env="CLICKUP_CLIENT_SECRET",
        mcp_status="needs_server",
        mcp_notes="Community npm `@taazkareem/clickup-mcp-server` (not officially published by ClickUp) as a starting point.",
    ),
    "monday": ConnectorConfig(
        id="monday", display_name="monday.com", category="Project Management",
        description="Read and manage your monday.com boards, items, and updates.",
        scopes=["boards:read", "boards:write", "users:read", "updates:read", "updates:write"],
        authorize_url="https://auth.monday.com/oauth2/authorize", token_url="https://auth.monday.com/oauth2/token",
        client_id_env="MONDAY_CLIENT_ID", client_secret_env="MONDAY_CLIENT_SECRET",
        transport="http", http_url="https://mcp.monday.com/mcp",
        mcp_notes="monday.com ships this MCP preinstalled on every account — a workspace admin may need to enable it under Admin > Permissions > AI Connectors first.",
    ),
    "basecamp": ConnectorConfig(
        id="basecamp", display_name="Basecamp", category="Project Management",
        description="Read and manage your Basecamp to-dos, messages, and schedule items.",
        scopes=[],
        authorize_url="https://launchpad.37signals.com/authorization/new", token_url="https://launchpad.37signals.com/authorization/token",
        client_id_env="BASECAMP_CLIENT_ID", client_secret_env="BASECAMP_CLIENT_SECRET",
        mcp_status="needs_server",
        mcp_notes="No mature official/community MCP server found — build a thin wrapper over the Basecamp REST API. Every request needs a descriptive User-Agent header with a contact email or Basecamp may rate-limit/reject it.",
    ),
    "airtable": ConnectorConfig(
        id="airtable", display_name="Airtable", category="Project Management",
        description="Read and manage your Airtable bases, tables, and records.",
        scopes=["data.records:read", "data.records:write", "schema.bases:read", "schema.bases:write", "user.email:read"],
        authorize_url="https://airtable.com/oauth2/v1/authorize", token_url="https://airtable.com/oauth2/v1/token",
        client_id_env="AIRTABLE_CLIENT_ID", client_secret_env="AIRTABLE_CLIENT_SECRET",
        mcp_status="needs_server",
        mcp_notes=("PKCE is MANDATORY on every authorize request (not optional) — oauth_service.py doesn't implement "
                   "PKCE yet, so this needs an engine change before it can work, not just a server. Community npm "
                   "`@felores/airtable-mcp-server` as a reference once PKCE support exists."),
    ),

    # ============== Developer Tools ==============
    "gitlab": ConnectorConfig(
        id="gitlab", display_name="GitLab", category="Developer Tools",
        description="Read and manage your GitLab projects, issues, merge requests, and repository content.",
        scopes=["read_api", "read_user", "read_repository"],
        authorize_url="https://gitlab.com/oauth/authorize", token_url="https://gitlab.com/oauth/token",
        client_id_env="GITLAB_CLIENT_ID", client_secret_env="GITLAB_CLIENT_SECRET",
        mcp_status="needs_server",
        mcp_notes="GitLab's own Duo MCP server is Beta and gated behind a Premium/Ultimate subscription with incomplete public endpoint docs — build a thin wrapper over the REST/GraphQL API instead.",
    ),
    "bitbucket": ConnectorConfig(
        id="bitbucket", display_name="Bitbucket", category="Developer Tools",
        description="Read and manage your Bitbucket Cloud repositories, pull requests, and pipelines.",
        scopes=["account", "repository", "pullrequest"],
        authorize_url="https://bitbucket.org/site/oauth2/authorize", token_url="https://bitbucket.org/site/oauth2/access_token",
        client_id_env="BITBUCKET_CLIENT_ID", client_secret_env="BITBUCKET_CLIENT_SECRET",
        mcp_status="needs_server",
        mcp_notes="No official Atlassian Bitbucket MCP server exists — community npm `@aashari/mcp-server-atlassian-bitbucket` is the most-used option; vet before depending on it.",
    ),
    "vercel": ConnectorConfig(
        id="vercel", display_name="Vercel", category="Developer Tools",
        description="Inspect and manage your Vercel projects, deployments, and environment variables.",
        auth_type="api_key", credential_fields=["access_token"], credential_env_map={"access_token": "VERCEL_ACCESS_TOKEN"},
        mcp_status="needs_server",
        mcp_notes=("Vercel runs an official hosted MCP (mcp.vercel.com) but it handles OAuth itself end-to-end — "
                   "doesn't accept a plain personal-access-token-as-bearer in this engine's generic http path. "
                   "Simplest fix: point users at mcp.vercel.com directly instead of proxying through this engine, "
                   "or build a thin stdio wrapper using the personal access token."),
    ),
    "aws": ConnectorConfig(
        id="aws", display_name="Amazon Web Services", category="Developer Tools",
        description="Call AWS APIs (S3, EC2, CloudWatch, Bedrock, etc.) using your own IAM credentials.",
        auth_type="api_key", credential_fields=["access_key_id", "secret_access_key", "region"],
        credential_env_map={"access_key_id": "AWS_ACCESS_KEY_ID", "secret_access_key": "AWS_SECRET_ACCESS_KEY", "region": "AWS_DEFAULT_REGION"},
        transport="stdio", stdio_command="uvx", stdio_args=["awslabs.aws-api-mcp-server@latest"],
        mcp_status="needs_server",
        mcp_notes=("Official AWS-published server (github.com/awslabs/mcp) reads the standard boto3 env vars used "
                   "here, which is promising, but this exact invocation hasn't been run/verified end-to-end yet — "
                   "verify before marking ready. Use a dedicated least-privilege IAM user, never root/admin credentials."),
    ),
    "azure": ConnectorConfig(
        id="azure", display_name="Microsoft Azure", category="Developer Tools",
        description="Call Azure APIs using a service principal from your own tenant.",
        auth_type="api_key", credential_fields=["tenant_id", "client_id", "client_secret", "subscription_id"],
        credential_env_map={"tenant_id": "AZURE_TENANT_ID", "client_id": "AZURE_CLIENT_ID", "client_secret": "AZURE_CLIENT_SECRET", "subscription_id": "AZURE_SUBSCRIPTION_ID"},
        transport="stdio", stdio_command="npx", stdio_args=["-y", "@azure/mcp@latest"],
        mcp_status="needs_server",
        mcp_notes=("Official Microsoft-published server reads the standard Azure Identity env vars used here, which "
                   "is promising, but this exact invocation hasn't been run/verified end-to-end yet. Scope the "
                   "service principal's role assignment as narrowly as possible (never Owner/Contributor at subscription scope)."),
    ),
    "gcp": ConnectorConfig(
        id="gcp", display_name="Google Cloud Platform", category="Developer Tools",
        description="Call GCP APIs (Cloud SQL, BigQuery, Storage, etc.) using a service account from your own project.",
        auth_type="api_key", credential_fields=["project_id", "service_account_json"],
        credential_env_map={"project_id": "GCP_PROJECT_ID", "service_account_json": "GOOGLE_APPLICATION_CREDENTIALS_JSON"},
        mcp_status="needs_server",
        mcp_notes=("Google's official MCP Toolbox for Databases (googleapis/genai-toolbox) covers Cloud SQL/Spanner/"
                   "BigQuery/Firestore specifically, not general GCP infra — no single official broad-infra MCP server "
                   "was found. Use a narrowly-scoped predefined IAM role, never Owner/Editor at project level."),
    ),
    "circleci": ConnectorConfig(
        id="circleci", display_name="CircleCI", category="Developer Tools",
        description="Inspect and manage your CircleCI pipelines, workflows, and job runs.",
        auth_type="api_key", credential_fields=["api_token"], credential_env_map={"api_token": "CIRCLECI_API_TOKEN"},
        mcp_status="needs_server",
        mcp_notes="CircleCI runs an official hosted MCP (mcp.circleci.com) but its own OAuth2 flow mandates a localhost-only loopback redirect (built for CLIs), not usable from a hosted web app — build a thin stdio wrapper using the Personal API Token instead.",
    ),
    "sentry": ConnectorConfig(
        id="sentry", display_name="Sentry", category="Developer Tools",
        description="Read and triage your Sentry issues, events, and project data.",
        scopes=["org:read", "project:read", "event:read", "issue:write"],
        authorize_url="https://sentry.io/oauth/authorize/", token_url="https://sentry.io/oauth/token/",
        client_id_env="SENTRY_CLIENT_ID", client_secret_env="SENTRY_CLIENT_SECRET",
        transport="http", http_url="https://mcp.sentry.dev/mcp",
    ),

    # ============== CRM & Support ==============
    "hubspot": ConnectorConfig(
        id="hubspot", display_name="HubSpot", category="CRM & Support",
        description="Read and write CRM objects (contacts, companies, deals, tickets) in your HubSpot account.",
        scopes=["oauth", "crm.objects.contacts.read", "crm.objects.contacts.write", "crm.objects.companies.read", "crm.objects.deals.read"],
        authorize_url="https://app.hubspot.com/oauth/authorize", token_url="https://api.hubapi.com/oauth/v3/token",
        client_id_env="HUBSPOT_CLIENT_ID", client_secret_env="HUBSPOT_CLIENT_SECRET",
        transport="http", http_url="https://mcp.hubspot.com",
        mcp_notes="Build the app as a Public app (not Private) for OAuth to work; unlisted apps are capped at 10 allowlisted accounts, fine for personal/internal use.",
    ),
    "salesforce": ConnectorConfig(
        id="salesforce", display_name="Salesforce", category="CRM & Support",
        description="Query and modify Salesforce CRM records (leads, accounts, opportunities, cases).",
        scopes=["api", "refresh_token", "offline_access"],
        authorize_url="https://login.salesforce.com/services/oauth2/authorize",
        token_url="https://login.salesforce.com/services/oauth2/token",
        client_id_env="SALESFORCE_CLIENT_ID", client_secret_env="SALESFORCE_CLIENT_SECRET",
        mcp_status="needs_server",
        mcp_notes=("Use test.salesforce.com instead of login.salesforce.com for sandbox orgs, or the org's My Domain "
                   "(now mandatory for new orgs) — this registry's static authorize_url doesn't vary per-org yet. "
                   "Salesforce's official MCP (GA) needs a separate External Client App with an mcp_api scope, distinct "
                   "from this standard REST connected app."),
    ),
    "intercom": ConnectorConfig(
        id="intercom", display_name="Intercom", category="CRM & Support",
        description="Read/respond to Intercom conversations and manage contacts/companies.",
        scopes=[],
        authorize_url="https://app.intercom.com/oauth", token_url="https://api.intercom.io/auth/eagle/token",
        client_id_env="INTERCOM_CLIENT_ID", client_secret_env="INTERCOM_CLIENT_SECRET",
        transport="http", http_url="https://mcp.intercom.com/mcp",
        mcp_notes="US-hosted workspaces only; EU/AU workspaces need https://app.eu.intercom.com/oauth or https://app.au.intercom.com/oauth as authorize_url instead.",
    ),
    "zendesk": ConnectorConfig(
        id="zendesk", display_name="Zendesk", category="CRM & Support",
        description="Read and manage Zendesk support tickets, users, and help center content.",
        scopes=["read", "write"],
        authorize_url="https://{subdomain}.zendesk.com/oauth/authorizations/new",
        token_url="https://{subdomain}.zendesk.com/oauth/tokens",
        client_id_env="ZENDESK_CLIENT_ID", client_secret_env="ZENDESK_CLIENT_SECRET",
        mcp_status="needs_server",
        mcp_notes=("authorize_url/token_url are templated per-customer subdomain — this registry's static-URL OAuth "
                   "flow doesn't support that yet (needs a per-connection subdomain field, an engine change). No "
                   "verified MCP package found either — build a thin REST wrapper once the subdomain support exists."),
    ),
    "freshdesk": ConnectorConfig(
        id="freshdesk", display_name="Freshdesk", category="CRM & Support",
        description="Read and manage Freshdesk tickets, contacts, and agents.",
        auth_type="api_key", credential_fields=["api_key", "domain"],
        credential_env_map={"api_key": "FRESHDESK_API_KEY", "domain": "FRESHDESK_DOMAIN"},
        mcp_status="needs_server",
        mcp_notes="No official MCP server — build a thin stdio wrapper (HTTP Basic auth, API key as username, any string as password).",
    ),
    "mailchimp": ConnectorConfig(
        id="mailchimp", display_name="Mailchimp", category="CRM & Support",
        description="Manage your Mailchimp audiences, campaigns, and templates.",
        scopes=[],
        authorize_url="https://login.mailchimp.com/oauth2/authorize", token_url="https://login.mailchimp.com/oauth2/token",
        client_id_env="MAILCHIMP_CLIENT_ID", client_secret_env="MAILCHIMP_CLIENT_SECRET",
        mcp_status="needs_server",
        mcp_notes=("No granular OAuth scopes — grants full account access. After token exchange, call "
                   "https://login.mailchimp.com/oauth2/metadata to discover the user's datacenter prefix (e.g. us6) "
                   "before making any API calls. No official MCP server found."),
    ),
    "sendgrid": ConnectorConfig(
        id="sendgrid", display_name="SendGrid", category="CRM & Support",
        description="Send transactional/marketing email and manage templates.",
        auth_type="api_key", credential_fields=["api_key"], credential_env_map={"api_key": "SENDGRID_API_KEY"},
        mcp_status="needs_server",
        mcp_notes="No OAuth exists for this use case, confirmed. No official SendGrid MCP server — build a thin stdio wrapper over the v3 Mail Send API.",
    ),
    "docusign": ConnectorConfig(
        id="docusign", display_name="DocuSign", category="CRM & Support",
        description="Create and send envelopes for e-signature and check signing status.",
        scopes=["signature"],
        authorize_url="https://account-d.docusign.com/oauth/auth", token_url="https://account-d.docusign.com/oauth/token",
        client_id_env="DOCUSIGN_CLIENT_ID", client_secret_env="DOCUSIGN_CLIENT_SECRET",
        mcp_status="needs_server",
        mcp_notes=("authorize_url/token_url above are the SANDBOX (account-d.docusign.com) endpoints — production "
                   "uses account.docusign.com after a Go-Live review. No official MCP server found."),
    ),

    # ============== Commerce, Social & Analytics ==============
    "stripe": ConnectorConfig(
        id="stripe", display_name="Stripe", category="Commerce & Finance",
        description="Read and manage your Stripe data (customers, charges, invoices, subscriptions, refunds).",
        auth_type="api_key", credential_fields=["secret_key"], credential_env_map={"secret_key": "STRIPE_SECRET_KEY"},
        mcp_status="needs_server",
        mcp_notes=("Stripe runs an official hosted MCP (mcp.stripe.com) and an official local toolkit "
                   "(@stripe/agent-toolkit, npm/PyPI) that takes the key directly — a good candidate to wire up next. "
                   "Use a restricted key (rk_), not the full secret key (sk_)."),
    ),
    "paypal": ConnectorConfig(
        id="paypal", display_name="PayPal", category="Commerce & Finance",
        description="Read and manage your PayPal business account (orders, invoices, payouts, transactions).",
        auth_type="api_key", credential_fields=["client_id", "client_secret", "mode"],
        credential_env_map={"client_id": "PAYPAL_CLIENT_ID", "client_secret": "PAYPAL_CLIENT_SECRET", "mode": "PAYPAL_MODE"},
        mcp_status="needs_server",
        mcp_notes=("PayPal's 3-legged 'Log in with PayPal' OAuth only grants identity scopes, not financial data — "
                   "this client_id+secret pair is exchanged server-side via the Client Credentials grant instead. "
                   "Official @paypal/mcp (npm) and hosted mcp.paypal.com / mcp.sandbox.paypal.com exist as references."),
    ),
    "shopify": ConnectorConfig(
        id="shopify", display_name="Shopify", category="Commerce & Finance",
        description="Manage your Shopify store (products, orders, customers, inventory).",
        auth_type="api_key", credential_fields=["shop_domain", "admin_api_access_token"],
        credential_env_map={"shop_domain": "SHOPIFY_SHOP_DOMAIN", "admin_api_access_token": "SHOPIFY_ADMIN_API_TOKEN"},
        mcp_status="needs_server",
        mcp_notes="Community npm `shopify-mcp` as a starting point. As of 2026-01-01 new custom apps must go through the Shopify Dev Dashboard with a 24h-expiring token instead of the legacy non-expiring one — verify current behavior for the specific store.",
    ),
    "quickbooks": ConnectorConfig(
        id="quickbooks", display_name="QuickBooks (Intuit)", category="Commerce & Finance",
        description="Read and manage your QuickBooks Online company data (invoices, bills, customers, reports).",
        scopes=["com.intuit.quickbooks.accounting"],
        authorize_url="https://appcenter.intuit.com/connect/oauth2", token_url="https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
        client_id_env="QUICKBOOKS_CLIENT_ID", client_secret_env="QUICKBOOKS_CLIENT_SECRET",
        mcp_status="needs_server",
        mcp_notes=("Refresh tokens are single-use/rotating — every refresh returns a new refresh_token that must be "
                   "saved immediately (oauth_service.py already does this generically). Community MCP packages exist "
                   "but no single canonical one was confirmed."),
    ),
    "twitter_x": ConnectorConfig(
        id="twitter_x", display_name="Twitter/X", category="Social Media",
        description="Read and post on your own X account.",
        scopes=["tweet.read", "tweet.write", "users.read", "offline.access"],
        authorize_url="https://x.com/i/oauth2/authorize", token_url="https://api.x.com/2/oauth2/token",
        client_id_env="X_CLIENT_ID", client_secret_env="X_CLIENT_SECRET",
        mcp_status="needs_server",
        mcp_notes="No official MCP server; X's API now requires a paid usage tier even after OAuth succeeds (free tier for new developers closed Feb 2026) — confirm current pricing before relying on this.",
    ),
    "linkedin": ConnectorConfig(
        id="linkedin", display_name="LinkedIn", category="Social Media",
        description="Read your LinkedIn profile and, where approved, post on your behalf.",
        scopes=["openid", "profile", "email", "w_member_social"],
        authorize_url="https://www.linkedin.com/oauth/v2/authorization", token_url="https://www.linkedin.com/oauth/v2/accessToken",
        client_id_env="LINKEDIN_CLIENT_ID", client_secret_env="LINKEDIN_CLIENT_SECRET",
        mcp_status="needs_server",
        mcp_notes=("w_member_social (posting) requires LinkedIn to approve your app for the relevant Product — not "
                   "instant, not guaranteed for small apps. No long-lived refresh tokens for most apps (60-day access "
                   "token, re-auth needed after). No official MCP server; avoid scraping-based community packages."),
    ),
    "reddit": ConnectorConfig(
        id="reddit", display_name="Reddit", category="Social Media",
        description="Read and post on your own Reddit account.",
        scopes=["identity", "read", "submit", "history"],
        authorize_url="https://www.reddit.com/api/v1/authorize", token_url="https://www.reddit.com/api/v1/access_token",
        client_id_env="REDDIT_CLIENT_ID", client_secret_env="REDDIT_CLIENT_SECRET",
        extra_authorize_params={"duration": "permanent"},
        mcp_status="needs_server",
        mcp_notes="Community PyPI `mcp-server-reddit` or npm `reddit-mcp-server` as a starting point. Requires a unique, descriptive User-Agent header on every API call or requests get throttled.",
    ),
    "google_analytics": ConnectorConfig(
        id="google_analytics", display_name="Google Analytics", category="Analytics",
        description="Read your GA4 property data (traffic reports, funnels, custom dimensions/metrics).",
        scopes=["https://www.googleapis.com/auth/analytics.readonly"],
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth", token_url="https://oauth2.googleapis.com/token",
        client_id_env="GOOGLE_CLIENT_ID", client_secret_env="GOOGLE_CLIENT_SECRET",
        extra_authorize_params={"access_type": "offline", "prompt": "consent"},
        transport="stdio", stdio_command="uvx", stdio_args=["google-analytics-mcp"],
        mcp_status="needs_server",
        mcp_notes="Official Google-published server (github.com/googleanalytics/google-analytics-mcp) — promising, but this exact invocation/env-var contract hasn't been verified end-to-end yet.",
    ),
}


def get_connector(connector_id: str) -> Optional[ConnectorConfig]:
    return CONNECTORS.get(connector_id)


def list_connectors() -> List[ConnectorConfig]:
    return list(CONNECTORS.values())


def connector_catalog_summary(connected_ids: "set[str]") -> str:
    """A compact, category-grouped list of every registered connector, marking
    which ones this user already has connected — fed into chat system prompts
    (services/ai_service.py, services/mcp/orchestrator_service.py) so Claude
    can proactively tell a user which service to connect for a request it
    can't currently fulfill, instead of refusing vaguely or making something up.
    """
    by_category: Dict[str, List[ConnectorConfig]] = {}
    for cfg in CONNECTORS.values():
        by_category.setdefault(cfg.category, []).append(cfg)

    lines = []
    for category in sorted(by_category):
        lines.append(f"{category}:")
        for cfg in by_category[category]:
            status = "connected" if cfg.id in connected_ids else "not connected"
            lines.append(f"  - {cfg.display_name} ({status}): {cfg.description}")
    return "\n".join(lines)
