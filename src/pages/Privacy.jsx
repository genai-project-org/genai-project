import { Link } from 'react-router-dom';
import { Sparkles } from 'lucide-react';

const LAST_UPDATED = 'August 19, 2026';

function Section({ title, children }) {
  return (
    <section className="mt-8">
      <h2 className="text-lg font-semibold text-foreground">{title}</h2>
      <div className="mt-2 space-y-3 text-sm leading-relaxed text-muted-foreground">
        {children}
      </div>
    </section>
  );
}

export default function Privacy() {
  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border">
        <div className="mx-auto flex max-w-3xl items-center gap-2 px-6 py-5">
          <Link to="/" className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary">
              <Sparkles className="h-4 w-4 text-primary-foreground" />
            </div>
            <span className="font-semibold text-foreground">
              IEMA<span className="text-primary">.</span>ai
            </span>
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-6 py-10">
        <h1 className="text-2xl font-bold text-foreground">Privacy Policy</h1>
        <p className="mt-2 text-sm text-muted-foreground">Last updated: {LAST_UPDATED}</p>

        <p className="mt-6 text-sm leading-relaxed text-muted-foreground">
          This policy explains what information IEMA.ai ("we", "us") collects when you use our
          apps and website (the "Service"), why we collect it, who we share it with, and the
          choices you have. It applies to the IEMA.ai mobile app (iOS and Android) and web app.
        </p>

        <Section title="Information we collect">
          <p><strong className="text-foreground">Account information.</strong> When you create an
          account, we collect your name and email address. If you sign in with Google, Apple,
          GitHub, or LinkedIn, we receive your name, email address, and profile photo from that
          provider, and a provider-issued identifier. If you register with email and password, we
          store a securely hashed version of your password — we never store or have access to your
          plain-text password.</p>
          <p><strong className="text-foreground">Content you create.</strong> Messages you send in
          chat, prompts and generated images/videos/summaries in AI Studio, résumé and career-tool
          inputs, and counseling chat messages are stored so you can access your history across
          sessions.</p>
          <p><strong className="text-foreground">Payment and credit information.</strong> We keep a
          record of your credit balance and transaction history (purchases, subscriptions, and
          usage). Card and payment details themselves are handled directly by our payment
          processors (Razorpay, and Apple/Google's in-app purchase systems) — we do not store your
          full card number.</p>
          <p><strong className="text-foreground">Device and usage data.</strong> We log technical
          information needed to keep your account secure, such as IP address, device/browser type,
          and sign-in timestamps.</p>
          <p><strong className="text-foreground">Photos and camera.</strong> If you attach an image
          to a chat, the app opens your device's native photo picker or camera — we only receive the
          specific photo you choose to share, never broad access to your photo library.</p>
        </Section>

        <Section title="How we use your information">
          <ul className="list-disc space-y-2 pl-5">
            <li>To provide and operate the Service — running your requests through AI providers,
            maintaining your chat/generation history, and managing your account and credit balance.</li>
            <li>To process payments and subscriptions.</li>
            <li>To send account-related emails (welcome, email verification, password reset codes).</li>
            <li>To detect abuse, enforce our content policies, and act on user reports of offensive
            AI-generated content.</li>
            <li>To improve the Service, including using aggregated, de-identified usage patterns.</li>
          </ul>
        </Section>

        <Section title="AI processing and third parties">
          <p>To generate responses, images, video, and summaries, your prompts and relevant content
          are sent to the AI providers that power those features — currently Anthropic (Claude),
          OpenAI, and Google (Gemini/Veo). These providers process your prompt to return a result;
          we do not control their independent data-handling practices, which are governed by their
          own policies.</p>
          <p>We also use the following service providers to operate IEMA.ai, each of whom processes
          data only as needed to provide their service to us:</p>
          <ul className="list-disc space-y-2 pl-5">
            <li><strong className="text-foreground">MongoDB Atlas</strong> — database hosting.</li>
            <li><strong className="text-foreground">Amazon Web Services (S3)</strong> — storage for
            generated images and videos.</li>
            <li><strong className="text-foreground">Resend</strong> — transactional email delivery.</li>
            <li><strong className="text-foreground">Razorpay, RevenueCat, Apple, and Google</strong> —
            payment and subscription processing.</li>
            <li><strong className="text-foreground">Google, Apple, GitHub, and LinkedIn</strong> — if
            you choose to sign in using one of these providers.</li>
          </ul>
          <p>We do not sell your personal information.</p>
        </Section>

        <Section title="Content reporting and moderation">
          <p>The app includes an in-app feature to report or flag AI-generated content you believe
          is offensive or inappropriate. Reports are reviewed by our team and used to inform content
          moderation. Reporting content does not remove it automatically — see the in-app report
          confirmation for details.</p>
        </Section>

        <Section title="Data retention and deletion">
          <p>We keep your account data for as long as your account is active. You can permanently
          delete your account at any time from the app (Settings → Danger zone) or the web app
          (Settings). Deleting your account removes your account record; associated usage history is
          deleted or disassociated from your identity on a rolling basis. If you'd like your data
          removed sooner, contact us using the details below.</p>
        </Section>

        <Section title="Children's privacy">
          <p>IEMA.ai is not directed at children under 13, and we do not knowingly collect personal
          information from children under 13. If you believe a child has provided us with personal
          information, please contact us and we will delete it.</p>
        </Section>

        <Section title="Security">
          <p>We use industry-standard measures to protect your information, including encrypted
          connections (HTTPS/TLS), hashed passwords, and access controls on our infrastructure. No
          method of transmission or storage is 100% secure, and we cannot guarantee absolute
          security.</p>
        </Section>

        <Section title="Your choices and rights">
          <ul className="list-disc space-y-2 pl-5">
            <li>Access or update your account details from Profile / Settings.</li>
            <li>Delete your account and associated data at any time.</li>
            <li>Unlink a connected sign-in provider from Settings, provided you have another way to
            sign in.</li>
            <li>Depending on where you live, you may have additional rights under laws like the
            GDPR or CCPA, including the right to request a copy of your data or object to certain
            processing — contact us to exercise these.</li>
          </ul>
        </Section>

        <Section title="Changes to this policy">
          <p>We may update this policy from time to time. We'll update the "Last updated" date above
          when we do, and for material changes we'll make reasonable efforts to notify you in the
          app.</p>
        </Section>

        <Section title="Contact us">
          <p>Questions about this policy or your data? Email us at{' '}
          <a href="mailto:privacy@iema.ai" className="text-primary hover:underline">privacy@iema.ai</a>.</p>
        </Section>
      </main>
    </div>
  );
}
