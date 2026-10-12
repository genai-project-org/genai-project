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
    # authorize_url/token_url may contain a "{domain}" placeholder when
    # requires_domain is set (e.g. Shopify, where every store has its own
    # OAuth host) — the user supplies that one non-secret value (their store
    # domain, not a credential) right before the popup opens; see
    # oauth_service.build_authorize_url's `domain` parameter.
    authorize_url: Optional[str] = None
    token_url: Optional[str] = None
    requires_domain: bool = False
    domain_label: str = "Domain"  # frontend prompt label when requires_domain is set
    domain_placeholder: str = ""
    client_id_env: Optional[str] = None
    client_secret_env: Optional[str] = None
    extra_authorize_params: Dict[str, str] = field(default_factory=dict)
    # stdio only: the single decrypted access token is injected under this
    # env var name (never as a CLI argument — that would leak into `ps`).
    token_env_var: Optional[str] = None
    # Some providers (Notion) want HTTP Basic client auth and/or a JSON body
    # on the token endpoint instead of form-encoded client_id/secret.
    token_basic_auth: bool = False
    token_request_json: bool = False
    # Scope list separator on the authorize URL (Linear wants commas, most want spaces).
    scope_sep: str = " "
    # Zendesk wants `scope` repeated on the token request.
    token_send_scope: bool = False
    # PKCE (S256). Mandatory for Airtable, on by default for Salesforce external client apps;
    # harmless where optional.
    pkce: bool = False
    # Providers whose refresh call needs a different URL than the code exchange (Basecamp).
    token_refresh_url: Optional[str] = None
    # requires_domain connectors whose host is "<sub>.<suffix>" (Zendesk): a bare
    # subdomain the user types is completed with this suffix.
    domain_suffix: str = ""

    # Generic REST fallback (services/mcp/servers/rest_server.py): used when the
    # provider has no usable hosted MCP server for a third-party OAuth token. The
    # model gets api_get/api_post/... tools locked to these hosts. rest_base may
    # contain {domain} / {instance_url} (taken from the saved connection) or
    # {cloudid} (resolved by rest_resolver at startup).
    rest_base: Optional[str] = None
    rest_allowed_hosts: List[str] = field(default_factory=list)
    rest_headers: Dict[str, str] = field(default_factory=dict)
    rest_resolver: str = ""

    # ---- api_key / redirect_token fields ----
    # api_key: the user pastes these values directly (no OAuth exists at the
    # provider at all).
    # redirect_token: a Trello-style flow — not standard OAuth2 (no client
    # secret, no server-side code exchange), but the per-user value still
    # arrives via a provider consent redirect the user approves in a popup,
    # never typed/copied by hand. `client_id_env` holds the operator's public
    # app key (not secret — safe to appear in the authorize URL);
    # credential_fields/credential_env_map describe the per-user value that
    # comes back in the redirect.
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

    def effective_scopes(self) -> List[str]:
        """Scopes to request. `<CONNECTOR_ID>_SCOPES` (space/comma separated) overrides the
        registry default — some providers (GitLab, Dropbox, Zoom) only accept scopes that are
        ticked on the operator's app, which the code can't know."""
        raw = os.environ.get(f"{self.id.upper()}_SCOPES", "").strip()
        if raw:
            return [x for x in raw.replace(",", " ").split() if x]
        return list(self.scopes)

    def client_id(self) -> str:
        return os.environ.get(self.client_id_env, "") if self.client_id_env else ""

    def client_secret(self) -> str:
        return os.environ.get(self.client_secret_env, "") if self.client_secret_env else ""

    def is_configured(self) -> bool:
        """Whether this server is ready to offer the connector at all.

        oauth2: the server-wide client_id/secret must be set. redirect_token:
        only the public app key (client_id_env) needs to be set — there's no
        secret. api_key: always true — there's nothing to configure
        server-side, each user supplies their own key(s) directly.
        """
        if self.auth_type == "api_key":
            return True
        if self.auth_type == "redirect_token":
            return bool(self.client_id())
        return bool(self.client_id() and self.client_secret())


REST_SERVER_ARGS = ["-m", "services.mcp.servers.rest_server"]
REST_TOKEN_ENV = "REST_ACCESS_TOKEN"


def _rest(**kw) -> dict:
    """Common ConnectorConfig kwargs for a connector served by the generic REST tool server."""
    return dict(transport="stdio", stdio_command=sys.executable, stdio_args=REST_SERVER_ARGS,
                token_env_var=REST_TOKEN_ENV, mcp_status="ready", **kw)


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
        transport="stdio", stdio_command=sys.executable,
        stdio_args=["-m", "services.mcp.servers.github_server"], token_env_var="GITHUB_ACCESS_TOKEN",
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
        authorize_url="https://api.notion.com/v1/oauth/authorize",
        token_url="https://api.notion.com/v1/oauth/token",
        client_id_env="NOTION_CLIENT_ID",
        client_secret_env="NOTION_CLIENT_SECRET",
        extra_authorize_params={"owner": "user"},
        # Notion's token endpoint wants HTTP Basic client auth + a JSON body.
        token_basic_auth=True, token_request_json=True,
        transport="stdio", stdio_command=sys.executable,
        stdio_args=["-m", "services.mcp.servers.notion_server"], token_env_var="NOTION_ACCESS_TOKEN",
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
        **_rest(rest_base="https://graph.microsoft.com/v1.0", rest_allowed_hosts=["graph.microsoft.com"]),
        mcp_notes="Microsoft Graph via the generic REST tool server.",
    ),
    "discord": ConnectorConfig(
        id="discord", display_name="Discord", category="Communication",
        description="See your Discord profile and servers (bot actions need a bot token, not yet supported).",
        # Without the `bot` scope this is a plain user-token flow; the user token can read /users/@me
        # and /users/@me/guilds. Posting/reading messages needs a platform bot token (not wired).
        scopes=["identify", "guilds"],
        authorize_url="https://discord.com/oauth2/authorize", token_url="https://discord.com/api/oauth2/token",
        client_id_env="DISCORD_CLIENT_ID", client_secret_env="DISCORD_CLIENT_SECRET",
        **_rest(rest_base="https://discord.com/api/v10", rest_allowed_hosts=["discord.com"]),
        mcp_notes="Limited to profile + server list with a user token; message actions need a bot token.",
    ),
    "zoom": ConnectorConfig(
        id="zoom", display_name="Zoom", category="Communication",
        description="Create and manage Zoom meetings on your behalf.",
        # Scopes are configured on the Zoom app itself; the authorize `scope` param is optional there.
        scopes=[],
        authorize_url="https://zoom.us/oauth/authorize", token_url="https://zoom.us/oauth/token",
        client_id_env="ZOOM_CLIENT_ID", client_secret_env="ZOOM_CLIENT_SECRET",
        token_basic_auth=True,  # Zoom requires HTTP Basic client auth on the token endpoint
        **_rest(rest_base="https://api.zoom.us/v2", rest_allowed_hosts=["api.zoom.us"]),
    ),
    "microsoft_outlook_mail": ConnectorConfig(
        id="microsoft_outlook_mail", display_name="Microsoft Outlook (Mail)", category="Communication",
        description="Read and send email through your Outlook/Microsoft 365 mailbox.",
        scopes=["offline_access", "User.Read", "Mail.Read", "Mail.Send"],
        authorize_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        client_id_env="MS_OUTLOOK_CLIENT_ID", client_secret_env="MS_OUTLOOK_CLIENT_SECRET",
        **_rest(rest_base="https://graph.microsoft.com/v1.0", rest_allowed_hosts=["graph.microsoft.com"]),
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
        **_rest(rest_base="https://docs.googleapis.com/v1", rest_allowed_hosts=["docs.googleapis.com", "www.googleapis.com"]),
    ),
    "google_sheets": ConnectorConfig(
        id="google_sheets", display_name="Google Sheets", category="Productivity & Docs",
        description="Read, create, and edit your Google Sheets spreadsheets.",
        scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive.file"],
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth", token_url="https://oauth2.googleapis.com/token",
        client_id_env="GOOGLE_CLIENT_ID", client_secret_env="GOOGLE_CLIENT_SECRET",
        extra_authorize_params={"access_type": "offline", "prompt": "consent"},
        **_rest(rest_base="https://sheets.googleapis.com/v4", rest_allowed_hosts=["sheets.googleapis.com", "www.googleapis.com"]),
    ),
    "google_drive": ConnectorConfig(
        id="google_drive", display_name="Google Drive", category="Productivity & Docs",
        description="Search, list, read, and upload files in your Google Drive.",
        scopes=["https://www.googleapis.com/auth/drive"],
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth", token_url="https://oauth2.googleapis.com/token",
        client_id_env="GOOGLE_CLIENT_ID", client_secret_env="GOOGLE_CLIENT_SECRET",
        extra_authorize_params={"access_type": "offline", "prompt": "consent"},
        **_rest(rest_base="https://www.googleapis.com/drive/v3", rest_allowed_hosts=["www.googleapis.com"]),
    ),
    "atlassian_confluence": ConnectorConfig(
        id="atlassian_confluence", display_name="Atlassian Confluence", category="Productivity & Docs",
        description="Search, read, and create/edit pages in your Confluence spaces.",
        scopes=["read:confluence-content.all", "read:confluence-space.summary", "write:confluence-content", "offline_access"],
        authorize_url="https://auth.atlassian.com/authorize", token_url="https://auth.atlassian.com/oauth/token",
        client_id_env="ATLASSIAN_CLIENT_ID", client_secret_env="ATLASSIAN_CLIENT_SECRET",
        extra_authorize_params={"audience": "api.atlassian.com", "prompt": "consent"},
        token_request_json=True,  # Atlassian's token endpoint takes a JSON body
        # 3LO tokens are not accepted by the hosted Rovo MCP, so go through the cloud REST gateway.
        **_rest(rest_base="https://api.atlassian.com/ex/confluence/{cloudid}/wiki/rest/api", rest_allowed_hosts=["api.atlassian.com"], rest_resolver="atlassian"),
        mcp_notes="Confluence Cloud REST API through api.atlassian.com; shares the OAuth app with Jira.",
    ),
    "microsoft_onedrive": ConnectorConfig(
        id="microsoft_onedrive", display_name="Microsoft OneDrive", category="Productivity & Docs",
        description="List, read, upload, and manage files in your OneDrive.",
        scopes=["Files.ReadWrite", "offline_access", "User.Read"],
        authorize_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        client_id_env="MS_GRAPH_CLIENT_ID", client_secret_env="MS_GRAPH_CLIENT_SECRET",
        **_rest(rest_base="https://graph.microsoft.com/v1.0", rest_allowed_hosts=["graph.microsoft.com"]),
    ),
    "microsoft_sharepoint": ConnectorConfig(
        id="microsoft_sharepoint", display_name="Microsoft SharePoint", category="Productivity & Docs",
        description="Read and edit documents/lists in your SharePoint Online sites.",
        scopes=["Sites.ReadWrite.All", "offline_access", "User.Read"],
        authorize_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        client_id_env="MS_GRAPH_CLIENT_ID", client_secret_env="MS_GRAPH_CLIENT_SECRET",
        **_rest(rest_base="https://graph.microsoft.com/v1.0", rest_allowed_hosts=["graph.microsoft.com"]),
        mcp_notes="Sites.ReadWrite.All may need tenant admin consent.",
    ),
    "dropbox": ConnectorConfig(
        id="dropbox", display_name="Dropbox", category="Productivity & Docs",
        description="List, read, upload, and manage files in your Dropbox.",
        # No scope param: Dropbox then grants whatever scopes are enabled on the app (a scope that is
        # not ticked in the app console makes authorize fail). Override with DROPBOX_SCOPES.
        scopes=[],
        authorize_url="https://www.dropbox.com/oauth2/authorize", token_url="https://api.dropboxapi.com/oauth2/token",
        client_id_env="DROPBOX_APP_KEY", client_secret_env="DROPBOX_APP_SECRET",
        extra_authorize_params={"token_access_type": "offline"},
        **_rest(rest_base="https://api.dropboxapi.com/2", rest_allowed_hosts=["api.dropboxapi.com", "content.dropboxapi.com"]),
        mcp_notes="Dropbox RPC endpoints (POST JSON, e.g. /files/list_folder) via the generic REST tool server.",
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
        scopes=[],  # default (full) scope
        authorize_url="https://app.asana.com/-/oauth_authorize", token_url="https://app.asana.com/-/oauth_token",
        client_id_env="ASANA_CLIENT_ID", client_secret_env="ASANA_CLIENT_SECRET",
        transport="stdio", stdio_command=sys.executable,
        stdio_args=["-m", "services.mcp.servers.asana_server"], token_env_var="ASANA_ACCESS_TOKEN",
    ),
    "linear": ConnectorConfig(
        id="linear", display_name="Linear", category="Project Management",
        description="Read and manage your Linear issues, projects, cycles, and comments.",
        scopes=["read", "write"], scope_sep=",",  # Linear wants comma-separated scopes
        authorize_url="https://linear.app/oauth/authorize", token_url="https://api.linear.app/oauth/token",
        client_id_env="LINEAR_CLIENT_ID", client_secret_env="LINEAR_CLIENT_SECRET",
        transport="stdio", stdio_command=sys.executable,
        stdio_args=["-m", "services.mcp.servers.linear_server"], token_env_var="LINEAR_ACCESS_TOKEN",
    ),
    "atlassian_jira": ConnectorConfig(
        id="atlassian_jira", display_name="Atlassian Jira", category="Project Management",
        description="Read and manage your Jira Cloud issues, projects, and comments.",
        scopes=["read:jira-work", "write:jira-work", "read:jira-user", "offline_access"],
        authorize_url="https://auth.atlassian.com/authorize", token_url="https://auth.atlassian.com/oauth/token",
        client_id_env="ATLASSIAN_CLIENT_ID", client_secret_env="ATLASSIAN_CLIENT_SECRET",
        extra_authorize_params={"audience": "api.atlassian.com", "prompt": "consent"},
        token_request_json=True,
        **_rest(rest_base="https://api.atlassian.com/ex/jira/{cloudid}/rest/api/3", rest_allowed_hosts=["api.atlassian.com"], rest_resolver="atlassian"),
        mcp_notes="Jira Cloud REST API through api.atlassian.com; shares the OAuth app with Confluence.",
    ),
    "trello": ConnectorConfig(
        id="trello", display_name="Trello", category="Project Management",
        description="Read and manage your Trello boards, lists, and cards.",
        # Not standard OAuth2 (no client secret, no server-side code exchange),
        # but still a pure click-Connect-and-approve flow from the user's
        # perspective: Trello redirects a popup back with the per-user token
        # already in the URL fragment — see services/mcp/oauth_service.py's
        # build_redirect_token_url(). client_id_env holds the operator's
        # public Trello API key (safe to appear in the authorize URL).
        auth_type="redirect_token",
        authorize_url="https://trello.com/1/authorize",
        client_id_env="TRELLO_API_KEY",
        credential_fields=["token"], credential_env_map={"token": "TRELLO_TOKEN"},
        transport="stdio", stdio_command=sys.executable,
        stdio_args=["-m", "services.mcp.servers.trello_server"],
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
        scopes=[],  # omit: monday then grants all scopes configured on the app
        authorize_url="https://auth.monday.com/oauth2/authorize", token_url="https://auth.monday.com/oauth2/token",
        client_id_env="MONDAY_CLIENT_ID", client_secret_env="MONDAY_CLIENT_SECRET",
        transport="http", http_url="https://mcp.monday.com/mcp",
        mcp_notes="monday.com ships this MCP preinstalled on every account — a workspace admin may need to enable it under Admin > Permissions > AI Connectors first.",
    ),
    "basecamp": ConnectorConfig(
        id="basecamp", display_name="Basecamp", category="Project Management",
        description="Read and manage your Basecamp to-dos, messages, and schedule items.",
        scopes=[],
        authorize_url="https://launchpad.37signals.com/authorization/new",
        token_url="https://launchpad.37signals.com/authorization/token?type=web_server",
        token_refresh_url="https://launchpad.37signals.com/authorization/token?type=refresh",
        client_id_env="BASECAMP_CLIENT_ID", client_secret_env="BASECAMP_CLIENT_SECRET",
        extra_authorize_params={"type": "web_server"},
        **_rest(rest_base="https://3.basecampapi.com/{cloudid}", rest_allowed_hosts=["3.basecampapi.com", "launchpad.37signals.com"],
                rest_resolver="basecamp", rest_headers={"User-Agent": "IEMA.ai (support@iema.ai)"}),
        mcp_notes="Basecamp 3/4 API; the account id is resolved from launchpad authorization.json.",
    ),
    "airtable": ConnectorConfig(
        id="airtable", display_name="Airtable", category="Project Management",
        description="Read and manage your Airtable bases, tables, and records.",
        scopes=["data.records:read", "data.records:write", "schema.bases:read"],
        authorize_url="https://airtable.com/oauth2/v1/authorize", token_url="https://airtable.com/oauth2/v1/token",
        client_id_env="AIRTABLE_CLIENT_ID", client_secret_env="AIRTABLE_CLIENT_SECRET",
        pkce=True, token_basic_auth=True,  # Airtable mandates PKCE and Basic client auth
        transport="stdio", stdio_command=sys.executable,
        stdio_args=["-m", "services.mcp.servers.airtable_server"], token_env_var="AIRTABLE_ACCESS_TOKEN",
    ),
    # ============== Developer Tools ==============
    "gitlab": ConnectorConfig(
        id="gitlab", display_name="GitLab", category="Developer Tools",
        description="Read and manage your GitLab projects, issues, merge requests, and repository content.",
        # Must be a subset of the scopes ticked on the GitLab application; override with GITLAB_SCOPES.
        scopes=["api", "read_user"],
        authorize_url="https://gitlab.com/oauth/authorize", token_url="https://gitlab.com/oauth/token",
        client_id_env="GITLAB_CLIENT_ID", client_secret_env="GITLAB_CLIENT_SECRET",
        **_rest(rest_base="https://gitlab.com/api/v4", rest_allowed_hosts=["gitlab.com"]),
    ),
    "bitbucket": ConnectorConfig(
        id="bitbucket", display_name="Bitbucket", category="Developer Tools",
        description="Read and manage your Bitbucket Cloud repositories, pull requests, and pipelines.",
        scopes=[],  # Bitbucket ignores the scope param; permissions are set on the OAuth consumer
        authorize_url="https://bitbucket.org/site/oauth2/authorize", token_url="https://bitbucket.org/site/oauth2/access_token",
        client_id_env="BITBUCKET_CLIENT_ID", client_secret_env="BITBUCKET_CLIENT_SECRET",
        token_basic_auth=True,
        **_rest(rest_base="https://api.bitbucket.org/2.0", rest_allowed_hosts=["api.bitbucket.org"]),
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
        description="Call Azure Resource Manager APIs on resources you have permission to manage.",
        # Delegated (user) access to Azure Resource Manager via the same Entra app as the Graph
        # connectors; the app needs the "Azure Service Management / user_impersonation" permission.
        scopes=["https://management.azure.com/user_impersonation", "offline_access"],
        authorize_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        client_id_env="MS_GRAPH_CLIENT_ID", client_secret_env="MS_GRAPH_CLIENT_SECRET",
        **_rest(rest_base="https://management.azure.com", rest_allowed_hosts=["management.azure.com"]),
        mcp_notes="ARM calls need an api-version query param.",
    ),
    "gcp": ConnectorConfig(
        id="gcp", display_name="Google Cloud Platform", category="Developer Tools",
        description="Call GCP APIs (Cloud SQL, BigQuery, Storage, etc.) on your own projects.",
        # cloud-platform is broad/sensitive; the user grants delegated access via the normal Google consent screen.
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth", token_url="https://oauth2.googleapis.com/token",
        client_id_env="GOOGLE_CLIENT_ID", client_secret_env="GOOGLE_CLIENT_SECRET",
        extra_authorize_params={"access_type": "offline", "prompt": "consent"},
        **_rest(rest_base="https://cloudresourcemanager.googleapis.com/v1", rest_allowed_hosts=["*.googleapis.com"]),
        mcp_notes="Any *.googleapis.com endpoint via the generic REST tool server; the API must be enabled on the user's project.",
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
        scopes=["org:read", "project:read", "event:read", "project:write"],
        authorize_url="https://sentry.io/oauth/authorize/", token_url="https://sentry.io/oauth/token/",
        client_id_env="SENTRY_CLIENT_ID", client_secret_env="SENTRY_CLIENT_SECRET",
        **_rest(rest_base="https://sentry.io/api/0", rest_allowed_hosts=["sentry.io"]),
        mcp_notes="Sentry REST API with the user's OAuth token (the hosted MCP runs its own OAuth and does not accept this token).",
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
        scopes=["api", "refresh_token"],
        authorize_url="https://login.salesforce.com/services/oauth2/authorize",
        token_url="https://login.salesforce.com/services/oauth2/token",
        client_id_env="SALESFORCE_CLIENT_ID", client_secret_env="SALESFORCE_CLIENT_SECRET",
        pkce=True,
        **_rest(rest_base="{instance_url}/services/data/v62.0", rest_allowed_hosts=["*.salesforce.com", "*.force.com"]),
        mcp_notes="Production/dev-edition orgs (login.salesforce.com); sandboxes need test.salesforce.com. instance_url comes from the token response.",
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
        authorize_url="https://{domain}/oauth/authorizations/new",
        token_url="https://{domain}/oauth/tokens",
        requires_domain=True, domain_label="Zendesk subdomain", domain_placeholder="yourcompany.zendesk.com",
        domain_suffix=".zendesk.com", token_request_json=True, token_send_scope=True,
        client_id_env="ZENDESK_CLIENT_ID", client_secret_env="ZENDESK_CLIENT_SECRET",
        **_rest(rest_base="https://{domain}/api/v2", rest_allowed_hosts=["*.zendesk.com"]),
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
        # Stripe Connect OAuth — Stripe's own recommended pattern for "let a third-party app
        # manage a user's Stripe account on their behalf", not the platform/marketplace-only
        # flow it's sometimes mistaken for. The user clicks Connect, logs into Stripe, approves,
        # and we get a per-account access token — no secret key ever typed by them.
        scopes=["read_write"],
        authorize_url="https://connect.stripe.com/oauth/authorize", token_url="https://connect.stripe.com/oauth/token",
        client_id_env="STRIPE_CONNECT_CLIENT_ID", client_secret_env="STRIPE_CONNECT_CLIENT_SECRET",
        mcp_status="needs_server",
        mcp_notes=("Enable Connect once under Stripe Dashboard > Settings > Connect to get a platform client_id "
                   "(ca_...). Official @stripe/agent-toolkit (npm/PyPI) and the hosted mcp.stripe.com both accept "
                   "the resulting per-account access token the same way they'd accept a secret key."),
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
        # Real OAuth2, but per-store: every shop has its own authorize/token
        # host, so the user supplies their store domain (not a secret) right
        # before the popup opens — see requires_domain / oauth_service.py's
        # `domain` parameter. One Shopify Partner app (operator-registered
        # once) works across every store that installs it.
        scopes=["read_products", "write_products", "read_orders", "write_orders", "read_customers"],
        authorize_url="https://{domain}/admin/oauth/authorize",
        token_url="https://{domain}/admin/oauth/access_token",
        requires_domain=True, domain_label="Store domain", domain_placeholder="yourstore.myshopify.com",
        client_id_env="SHOPIFY_CLIENT_ID", client_secret_env="SHOPIFY_CLIENT_SECRET",
        mcp_status="needs_server",
        mcp_notes=("Community npm `shopify-mcp` as a starting point. As of 2026-01-01 new custom/public apps get a "
                   "24h-expiring access token instead of the legacy non-expiring one — oauth_service.py's generic "
                   "refresh path only engages if Shopify's token response includes expires_in; verify current "
                   "behavior before relying on long-lived access."),
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
        client_id_env="LINKEDIN_MCP_CLIENT_ID", client_secret_env="LINKEDIN_MCP_CLIENT_SECRET",
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
        **_rest(rest_base="https://analyticsdata.googleapis.com/v1beta", rest_allowed_hosts=["analyticsdata.googleapis.com", "analyticsadmin.googleapis.com"]),
        mcp_notes="GA4 Data API (runReport) and Admin API (accountSummaries) via the generic REST tool server.",
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
