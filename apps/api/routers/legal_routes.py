"""Legal/static pages served directly by the API — no separate frontend
deploy dependency, since the mobile app links here using the API's own
origin (see mobile SettingsScreen.js / LoginScreen.js / RegisterScreen.js)."""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["legal"])

LAST_UPDATED = "August 19, 2026"

PRIVACY_HTML = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Privacy Policy — IEMA.ai</title>
<style>
  body {{ margin:0; background:#0a0a0f; color:#e5e5e5; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; }}
  .wrap {{ max-width:720px; margin:0 auto; padding:48px 24px 80px; }}
  .brand {{ display:flex; align-items:center; gap:8px; margin-bottom:32px; font-weight:600; font-size:18px; }}
  .brand .dot {{ color:#3b82f6; }}
  h1 {{ font-size:28px; margin:0 0 8px; color:#fff; letter-spacing:-0.02em; }}
  .updated {{ color:#71717a; font-size:14px; margin-bottom:32px; }}
  h2 {{ font-size:18px; color:#fff; margin:32px 0 8px; }}
  p, li {{ color:#a1a1aa; line-height:1.7; font-size:14px; }}
  ul {{ padding-left:20px; }}
  strong {{ color:#e5e5e5; }}
  a {{ color:#3b82f6; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="brand"><span>&#9632;</span> IEMA<span class="dot">.</span>ai</div>
  <h1>Privacy Policy</h1>
  <div class="updated">Last updated: {LAST_UPDATED}</div>

  <p>This policy explains what information IEMA.ai ("we", "us") collects when you use our apps
  and website (the "Service"), why we collect it, who we share it with, and the choices you have.
  It applies to the IEMA.ai mobile app (iOS and Android) and web app.</p>

  <h2>Information we collect</h2>
  <p><strong>Account information.</strong> When you create an account, we collect your name and
  email address. If you sign in with Google, Apple, GitHub, or LinkedIn, we receive your name,
  email address, and profile photo from that provider, and a provider-issued identifier. If you
  register with email and password, we store a securely hashed version of your password — we
  never store or have access to your plain-text password.</p>
  <p><strong>Content you create.</strong> Messages you send in chat, prompts and generated
  images/videos/summaries in AI Studio, résumé and career-tool inputs, and counseling chat
  messages are stored so you can access your history across sessions.</p>
  <p><strong>Payment and credit information.</strong> We keep a record of your credit balance and
  transaction history (purchases, subscriptions, and usage). Card and payment details themselves
  are handled directly by our payment processors (Razorpay, and Apple/Google's in-app purchase
  systems) — we do not store your full card number.</p>
  <p><strong>Device and usage data.</strong> We log technical information needed to keep your
  account secure, such as IP address, device/browser type, and sign-in timestamps.</p>
  <p><strong>Photos and camera.</strong> If you attach an image to a chat, the app opens your
  device's native photo picker or camera — we only receive the specific photo you choose to
  share, never broad access to your photo library.</p>

  <h2>How we use your information</h2>
  <ul>
    <li>To provide and operate the Service — running your requests through AI providers,
    maintaining your chat/generation history, and managing your account and credit balance.</li>
    <li>To process payments and subscriptions.</li>
    <li>To send account-related emails (welcome, email verification, password reset codes).</li>
    <li>To detect abuse, enforce our content policies, and act on user reports of offensive
    AI-generated content.</li>
    <li>To improve the Service, including using aggregated, de-identified usage patterns.</li>
  </ul>

  <h2>AI processing and third parties</h2>
  <p>To generate responses, images, video, and summaries, your prompts and relevant content are
  sent to the AI providers that power those features — currently Anthropic (Claude), OpenAI, and
  Google (Gemini/Veo). These providers process your prompt to return a result; we do not control
  their independent data-handling practices, which are governed by their own policies.</p>
  <p>We also use the following service providers to operate IEMA.ai, each of whom processes data
  only as needed to provide their service to us:</p>
  <ul>
    <li><strong>MongoDB Atlas</strong> — database hosting.</li>
    <li><strong>Amazon Web Services (S3)</strong> — storage for generated images and videos.</li>
    <li><strong>Resend</strong> — transactional email delivery.</li>
    <li><strong>Razorpay, RevenueCat, Apple, and Google</strong> — payment and subscription processing.</li>
    <li><strong>Google, Apple, GitHub, and LinkedIn</strong> — if you choose to sign in using one of these providers.</li>
  </ul>
  <p>We do not sell your personal information.</p>

  <h2>Content reporting and moderation</h2>
  <p>The app includes an in-app feature to report or flag AI-generated content you believe is
  offensive or inappropriate. Reports are reviewed by our team and used to inform content
  moderation.</p>

  <h2>Data retention and deletion</h2>
  <p>We keep your account data for as long as your account is active. You can permanently delete
  your account at any time from the app (Settings → Danger zone) or the web app (Settings).
  Deleting your account removes your account record; associated usage history is deleted or
  disassociated from your identity on a rolling basis. If you'd like your data removed sooner,
  contact us using the details below.</p>

  <h2>Children's privacy</h2>
  <p>IEMA.ai is not directed at children under 13, and we do not knowingly collect personal
  information from children under 13. If you believe a child has provided us with personal
  information, please contact us and we will delete it.</p>

  <h2>Security</h2>
  <p>We use industry-standard measures to protect your information, including encrypted
  connections (HTTPS/TLS), hashed passwords, and access controls on our infrastructure. No method
  of transmission or storage is 100% secure, and we cannot guarantee absolute security.</p>

  <h2>Your choices and rights</h2>
  <ul>
    <li>Access or update your account details from Profile / Settings.</li>
    <li>Delete your account and associated data at any time.</li>
    <li>Unlink a connected sign-in provider from Settings, provided you have another way to sign in.</li>
    <li>Depending on where you live, you may have additional rights under laws like the GDPR or
    CCPA, including the right to request a copy of your data or object to certain processing —
    contact us to exercise these.</li>
  </ul>

  <h2>Changes to this policy</h2>
  <p>We may update this policy from time to time. We'll update the "Last updated" date above when
  we do, and for material changes we'll make reasonable efforts to notify you in the app.</p>

  <h2>Contact us</h2>
  <p>Questions about this policy or your data? Email us at
  <a href="mailto:privacy@iema.ai">privacy@iema.ai</a>.</p>
</div>
</body>
</html>"""


@router.get("/privacy", response_class=HTMLResponse, include_in_schema=False)
async def privacy_policy():
    return HTMLResponse(content=PRIVACY_HTML)
