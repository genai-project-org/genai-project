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


class RazorpayVerifyRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


# ================= NOTIFICATIONS =================
class Notification(BaseDocument):
    user_id: str
    title: str
    body: str = ""
    kind: Literal["info", "success", "warning", "security", "low_credits", "purchase", "announcement"] = "info"
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
