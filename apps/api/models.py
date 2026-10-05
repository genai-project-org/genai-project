"""Pydantic models for IEMA.ai."""
from datetime import datetime
from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from db import BaseDocument, now_utc


# ================= USER =================
class User(BaseDocument):
    email: str
    name: str
    password_hash: Optional[str] = None
    role: Literal["user", "admin"] = "user"
    avatar: Optional[str] = None
    provider: Literal["email", "google", "apple", "microsoft", "facebook", "github", "linkedin"] = "email"
    provider_id: Optional[str] = None
    linked_accounts: list = Field(default_factory=list)  # [{"provider","provider_id","email","connected_at"}]
    plan: str = "free"
    plan_since: Optional[str] = None
    ai_provider: str = "iema"  # iema | claude | openai
    email_verified: bool = False
    theme: Literal["light", "dark", "system"] = "system"
    is_active: bool = True
    last_login_at: Optional[str] = None
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())
    updated_at: str = Field(default_factory=lambda: now_utc().isoformat())


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    name: str = Field(min_length=1, max_length=80)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class OAuthCodeRequest(BaseModel):
    code: str
    redirect_uri: str


class GoogleIdTokenRequest(BaseModel):
    credential: str  # Google-issued JWT id_token from GIS


class IdTokenRequest(BaseModel):
    id_token: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserPublic(BaseModel):
    id: str
    email: str
    name: str
    role: str
    avatar: Optional[str] = None
    provider: str
    email_verified: bool
    theme: str
    created_at: str
    plan: str = "free"
    ai_provider: str = "iema"


# ================= WALLET & CREDITS =================
class Wallet(BaseDocument):
    user_id: str
    welcome_credits: float = 0
    daily_credits: float = 0
    bonus_credits: float = 0
    referral_credits: float = 0
    purchased_credits: float = 0
    promotional_credits: float = 0
    last_daily_refill_at: Optional[str] = None
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())
    updated_at: str = Field(default_factory=lambda: now_utc().isoformat())

    @property
    def total(self) -> float:
        return (
            self.welcome_credits
            + self.daily_credits
            + self.bonus_credits
            + self.referral_credits
            + self.promotional_credits
            + self.purchased_credits
        )


class CreditTransaction(BaseDocument):
    user_id: str
    amount: float  # positive = credit, negative = debit
    balance_after: float
    bucket: Literal["welcome", "daily", "bonus", "referral", "purchased", "promotional", "mixed"] = "mixed"
    kind: Literal["signup_bonus", "daily_refill", "ai_usage", "purchase", "refund", "admin_adjust", "referral", "promo"] = "ai_usage"
    description: str = ""
    ref_id: Optional[str] = None  # conversation_id, payment_id, etc.
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())


# ================= CHAT =================
class Conversation(BaseDocument):
    user_id: str
    title: str = "New Chat"
    pinned: bool = False
    folder: Optional[str] = None
    model_used: Optional[str] = None
    provider_used: Optional[str] = None
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())
    updated_at: str = Field(default_factory=lambda: now_utc().isoformat())


class Message(BaseDocument):
    conversation_id: str
    user_id: str
    role: Literal["user", "assistant", "system"]
    content: str
    provider: Optional[str] = None
    model: Optional[str] = None
    credits_used: float = 0
    tokens_in: int = 0
    tokens_out: int = 0
    attachments: List[Dict[str, Any]] = Field(default_factory=list)
    flagged: bool = False  # personal bookmark; drives the "Flagged Prompts" sidebar list
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=32000)
    conversation_id: Optional[str] = None
    model: Optional[str] = None  # optional model override
    attachments: Optional[List[Dict[str, Any]]] = None  # [{url, content_type, filename}]


class RenameConversationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)


# ================= EMAIL VERIFY / RESET =================
class SendVerifyRequest(BaseModel):
    pass  # uses current user from token


class VerifyEmailRequest(BaseModel):
    code: str = Field(min_length=4, max_length=8)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=6, max_length=128)


# ================= CREDIT PACKS =================
class CreditPack(BaseDocument):
    name: str
    slug: str
    description: str = ""
    price: float
    currency: str = "usd"  # 'usd' or 'inr'
    credits: float
    bonus_credits: float = 0
    is_popular: bool = False
    is_visible: bool = True
    sort_order: int = 0
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())


class CreditPackCreate(BaseModel):
    name: str
    slug: str
    description: str = ""
    price: float
    currency: str = "usd"
    credits: float
    bonus_credits: float = 0
    is_popular: bool = False
    is_visible: bool = True
    sort_order: int = 0


# ================= PAYMENTS =================
class PaymentTransaction(BaseDocument):
    user_id: str
    provider: Literal["stripe", "razorpay"]
    pack_slug: str
    amount: float
    currency: str
    credits: float  # total credits including bonus
    session_id: Optional[str] = None  # stripe session id
    order_id: Optional[str] = None  # razorpay order id
    payment_id: Optional[str] = None  # razorpay payment id
    status: Literal["initiated", "pending", "paid", "failed", "expired", "refunded"] = "initiated"
    metadata: Dict[str, Any] = Field(default_factory=dict)
    credited: bool = False
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())
    updated_at: str = Field(default_factory=lambda: now_utc().isoformat())


class StripeCheckoutRequest(BaseModel):
    pack_slug: str
    origin_url: str


class RazorpayOrderRequest(BaseModel):
    pack_slug: str
    discount_code: Optional[str] = None
    # "credits" (default) looks the slug up in credit_packs_col and tops up the
    # wallet on payment; "interview_sessions" looks it up in interview_packs_col
    # and grants Mock Interview entitlements instead — the two are deliberately
    # non-fungible, see services/interview_service.py.
    pack_kind: Literal["credits", "interview_sessions"] = "credits"


class RazorpayVerifyRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


# ================= NOTIFICATIONS =================
class Notification(BaseDocument):
    user_id: str
    title: str
    body: str = ""
    kind: Literal["info", "success", "warning", "security", "low_credits", "purchase", "announcement", "job_match"] = "info"
    read: bool = False
    action_url: Optional[str] = None
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())


# ================= ADMIN =================
class AdminUpdateWalletRequest(BaseModel):
    user_id: str
    amount: float
    bucket: Literal["welcome", "daily", "bonus", "referral", "purchased", "promotional"] = "bonus"
    description: str = "Admin adjustment"


class UserUpdateRequest(BaseModel):
    name: Optional[str] = None
    theme: Optional[str] = None
    avatar: Optional[str] = None
    ai_provider: Optional[str] = None


# ================= CONTENT REPORTS =================
# Backs the in-app "Report" / "Flag" feature required by Google Play's
# AI-Generated Content policy: users must be able to flag offensive AI
# output without leaving the app, and those flags must feed moderation.
class ContentReport(BaseDocument):
    user_id: str
    content_type: str  # studio_image | studio_video | studio_summarize | chat | career | builder | counseling | other
    content_ref: Optional[str] = None  # url or id of the reported content
    content_preview: Optional[str] = None  # short excerpt/prompt for moderator context
    reason: str = "inappropriate_or_offensive"
    status: Literal["open", "reviewed", "dismissed"] = "open"
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())


class ReportContentRequest(BaseModel):
    content_type: str = Field(min_length=1, max_length=40)
    content_ref: Optional[str] = Field(default=None, max_length=2048)
    content_preview: Optional[str] = Field(default=None, max_length=500)
    reason: Optional[str] = Field(default="inappropriate_or_offensive", max_length=100)


class ReportStatusUpdateRequest(BaseModel):
    status: Literal["open", "reviewed", "dismissed"]


# ================= MCP ORCHESTRATION ENGINE =================
class McpConnection(BaseDocument):
    user_id: str
    connector_id: str
    # Encrypted JSON blob — shape depends on the connector's auth_type:
    # oauth2 -> {"access_token": "...", "refresh_token": "..."} (refresh_token omitted if the
    #   provider doesn't issue one); api_key -> {field: value, ...} for whatever
    #   services.mcp.registry.ConnectorConfig.credential_fields lists for that connector.
    credentials_enc: str
    token_expiry: Optional[str] = None  # oauth2 only; None = non-expiring token
    scopes: List[str] = Field(default_factory=list)
    external_label: Optional[str] = None  # e.g. connected email / workspace name, for display
    enabled: bool = True  # user-facing on/off switch — disabling hides this connector's tools from Claude without disconnecting it
    connected_at: str = Field(default_factory=lambda: now_utc().isoformat())
    updated_at: str = Field(default_factory=lambda: now_utc().isoformat())


class McpConnectorPublic(BaseModel):
    id: str
    display_name: str
    description: str
    category: str
    auth_type: str  # "oauth2" | "api_key" — tells the frontend which Connect UI to render
    mcp_status: str  # "ready" | "needs_server" — whether prompts can actually use this connector yet
    credential_fields: List[str] = Field(default_factory=list)  # api_key connectors only
    scopes: List[str]
    connected: bool
    enabled: bool = True
    external_label: Optional[str] = None
    configured: bool  # whether the server has this connector's OAuth app credentials set (oauth2 only)


class McpCallbackRequest(BaseModel):
    code: str
    state: str
    redirect_uri: str


class McpToggleRequest(BaseModel):
    enabled: bool


class McpApiKeyConnectRequest(BaseModel):
    values: Dict[str, str]


class McpPromptRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)


# ================= RESUME PROFILE (persisted CV, shared by Resume Intelligence,
# Career Intelligence and Mock Interviews) =================
class ResumeProfile(BaseDocument):
    user_id: str
    raw_text: str
    structured: Dict[str, Any] = Field(default_factory=dict)  # skills, years_experience, work_history, projects, education, certifications
    ats_score: Optional[int] = None
    shortlist_chance: Optional[int] = None
    source: Literal["upload", "paste"] = "upload"
    filename: Optional[str] = None
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())
    updated_at: str = Field(default_factory=lambda: now_utc().isoformat())


class ResumeProfilePublic(BaseModel):
    id: str
    structured: Dict[str, Any]
    ats_score: Optional[int] = None
    shortlist_chance: Optional[int] = None
    source: str
    filename: Optional[str] = None
    updated_at: str


# ================= MOCK INTERVIEW =================
InterviewTopic = Literal["dsa", "hld", "lld", "design", "hr"]
InterviewRound = Literal["technical", "behavioral"]
InterviewSessionStatus = Literal[
    "created", "technical_in_progress", "behavioral_in_progress",
    "completed", "terminated_violations", "terminated_error", "abandoned", "expired",
]
DEFAULT_INTERVIEW_LANGUAGES = ["python", "javascript", "cpp", "java"]  # matches practice_service.LANGUAGE_RUNTIMES


class InterviewPackConfig(BaseModel):
    """The format a pack grants — snapshotted onto each entitlement grant at
    purchase/admin-grant time (see interview_entitlement_grants_col), so later
    edits to the pack's config never retroactively change an already-granted
    batch of sessions. This is the "coarse" configuration knob: what a
    candidate can choose FROM at session setup is bounded by whichever grant's
    config they pick to consume — see InterviewSessionCreateRequest below for
    the "fine" per-session choices made within these bounds.
    """
    technical_minutes: int = 45
    behavioral_minutes: int = 15  # 0 = this pack's sessions have no behavioral round at all
    topics: List[InterviewTopic] = Field(default_factory=lambda: ["dsa", "hld", "lld", "design", "hr"])
    seniority_levels: List[str] = Field(default_factory=lambda: ["entry", "mid", "senior"])
    languages: List[str] = Field(default_factory=lambda: list(DEFAULT_INTERVIEW_LANGUAGES))  # coding-round language choices
    # topic -> list of focus areas the candidate can narrow into, e.g.
    # {"dsa": ["arrays_hashing", "two_pointers", "graphs", "dynamic_programming"]}.
    # A topic with no entry here (or an empty list) simply has no sub-topic
    # picker — the agent covers that topic broadly instead.
    sub_topics: Dict[str, List[str]] = Field(default_factory=dict)


class InterviewPack(BaseDocument):
    name: str
    slug: str
    description: str = ""
    price: float
    currency: str = "usd"
    sessions_included: int
    config: InterviewPackConfig = Field(default_factory=InterviewPackConfig)
    is_popular: bool = False
    is_visible: bool = True
    sort_order: int = 0
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())


class InterviewPackCreate(BaseModel):
    name: str
    slug: str
    description: str = ""
    price: float
    currency: str = "usd"
    sessions_included: int
    config: InterviewPackConfig = Field(default_factory=InterviewPackConfig)
    is_popular: bool = False
    is_visible: bool = True
    sort_order: int = 0


class InterviewSessionCreateRequest(BaseModel):
    # Which owned entitlement grant (i.e. which purchased pack's format) to
    # consume. Optional ONLY for admins — see interview_service.create_session's
    # docstring for the admin no-pack testing bypass; a non-admin omitting
    # this gets a 400.
    grant_id: Optional[str] = None
    topic: InterviewTopic
    seniority: str = "mid"  # must be one of the grant's config.seniority_levels
    sub_topic: Optional[str] = None  # must be one of the grant's config.sub_topics[topic], if that list is non-empty
    language: Optional[str] = None  # coding-round language; must be one of the grant's config.languages
    include_behavioral: Optional[bool] = None  # None = use the grant's default (True iff behavioral_minutes > 0); explicit False skips it even if the pack includes it
    # Candidate-adjustable to fit their actual available time — None = use the
    # grant's config default. Bounded server-side by interview_service's
    # MIN/MAX_TECHNICAL_MINUTES / MIN/MAX_BEHAVIORAL_MINUTES regardless of pack.
    technical_minutes: Optional[int] = None
    behavioral_minutes: Optional[int] = None
    resume_profile_id: Optional[str] = None  # defaults to the caller's own profile if omitted


class InterviewLanguageChangeRequest(BaseModel):
    language: Literal["python", "javascript", "cpp", "java"]


class InterviewViolationType(BaseModel):
    type: Literal[
        "face_not_visible", "multiple_faces", "tab_blur", "fullscreen_exit",
        "copy_paste", "devtools_suspected", "app_backgrounded",
    ]
    detected_at: Optional[str] = None  # client clock, informational only — never trusted for logic


class AdminGrantInterviewSessionsRequest(BaseModel):
    user_id: str
    sessions: int
    pack_id: Optional[str] = None  # which pack's config to snapshot onto this grant; falls back to a sane default if omitted
    description: str = "Admin grant"
