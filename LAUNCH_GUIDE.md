# IEMA.ai Mobile — Launch & IAP Setup Guide

This guide covers **(1)** how to preview the Expo app right now, and **(2)** how to
register in-app-purchase products in **Apple App Store Connect** and
**Google Play Console** so backend `iap/apple/verify` and `iap/google/verify`
endpoints succeed.

---

## 1. Preview the Expo app

The mobile app lives at `/app/mobile`. It already points at your production
backend via `EXPO_PUBLIC_API_URL` in `mobile/.env` (or `app.json` `extra`).

### Fastest: Expo Go on your phone
```bash
cd /app/mobile
yarn install            # first time only
npx expo start          # opens Metro bundler; scan QR with Expo Go
```
- iOS: install **Expo Go** from App Store, open Camera, scan QR.
- Android: install **Expo Go** from Play Store, tap "Scan QR" inside Expo Go.

You will be able to sign in, chat, use Studio/Career/Counseling/Builder,
buy credits (Razorpay web checkout opens in browser), and see notifications.
**Native IAP is disabled in Expo Go** (only works in a real build — see step 2).

### Production preview: EAS build
```bash
cd /app/mobile
npm i -g eas-cli
eas login                # once
eas build:configure      # once — creates eas.json
eas build --profile preview --platform ios       # or android
```
- After ~15 min you'll get an installable link (`.ipa` via TestFlight,
  `.apk`/`.aab` for Android).
- TestFlight = internal testers can install without App Store review.

---

## 2. Register IAP products

The backend already accepts and verifies receipts. It maps
**product IDs → IEMA plan IDs** in
`/app/backend/services/payments_service.py` → `DEFAULT_PRODUCT_MAP`:

| Store Product ID       | IEMA Plan     | Cadence  |
|------------------------|---------------|----------|
| `iema.pro.monthly`     | `pro`         | monthly  |
| `iema.pro.annual`      | `pro_annual`  | annual   |
| `iema.team.monthly`    | `team`        | monthly  |
| `iema.team.annual`     | `team_annual` | annual   |

Use these **exact** IDs on both stores or your webhook won't credit users.

### 2a. Apple App Store Connect

1. Sign in at https://appstoreconnect.apple.com/
2. **My Apps → IEMA.ai → Monetization → Subscriptions**
3. Create a Subscription Group called `IEMA_AI_PLANS` (only needed once).
4. Add subscription products:
   - Reference name: **IEMA Pro Monthly**, Product ID: `iema.pro.monthly`,
     Duration: 1 Month, Price: pick a tier close to your $19.99 target.
   - Same for `iema.pro.annual` (1 Year), `iema.team.monthly`, `iema.team.annual`.
5. For each product: fill Localizations (name + description),
   Review Screenshot (1024×1024 marketing image), Review Notes.
6. **App-Specific Shared Secret**: App Store Connect → Users and Access →
   Keys → App Store Connect API → view your **Shared Secret**. Copy it into
   `APPLE_APP_STORE_SHARED_SECRET` in `/app/backend/.env` (already populated —
   verify it matches: `939b9b2529544f6492eeb636262faeac`).
7. Products stay in **Ready to Submit** state until your first app binary is
   sent for review. To test with **Sandbox** users:
   - App Store Connect → Users and Access → **Sandbox Testers** → add a
     tester with a fresh email.
   - On the test device: Settings → App Store → Sandbox Account → sign in.
   - Purchases go through the sandbox environment and the backend
     auto-falls-back to `sandbox.itunes.apple.com/verifyReceipt` on
     status 21007 (already coded).

### 2b. Google Play Console

1. Sign in at https://play.google.com/console/
2. **All apps → IEMA.ai → Monetize → Products → Subscriptions**
3. Create subscription products with these IDs and one base plan each:
   - `iema.pro.monthly` — Base plan `p1m` (auto-renewing, 1 month, prepaid off).
   - `iema.pro.annual` — Base plan `p1y` (1 year).
   - `iema.team.monthly` — Base plan `p1m`.
   - `iema.team.annual` — Base plan `p1y`.
4. For each subscription: set price for each country, add tags/benefits,
   activate the base plan.
5. **Service Account for verification** (backend uses this to call
   `androidpublisher.purchases.subscriptions.get`):
   - The service account JSON is already at
     `/app/backend/credentials/google-play-sa.json` and referenced from
     `.env` via `GOOGLE_PLAY_SA_JSON`.
   - Grant it access in Play Console: **Users and permissions → Invite user**
     → email of the service account (from JSON `client_email`) → grant
     **Financial data / View financial reports** + **Manage orders and
     subscriptions** at the app level.
   - Also link Play Console to a Google Cloud project that has the
     **Google Play Android Developer API** enabled.
6. **License Testers** for internal testing without payment charges:
   Setup → License testing → add your Gmail account.
7. Publish an **Internal test track** binary from EAS build; testers install
   the track link and can buy the products (charged nominal amount that
   Google auto-refunds).

### 2c. Wire the mobile app to purchase

`react-native-iap` is the standard bridge. Add it to `/app/mobile`:
```bash
cd /app/mobile
yarn add react-native-iap
```
In `mobile/src/screens/BillingScreen.js` add:
```js
import * as RNIap from 'react-native-iap';
// in useEffect: RNIap.initConnection()
// on tap: RNIap.requestSubscription({sku:'iema.pro.monthly'})
// in purchase listener → POST /api/payments/iap/apple/verify with base64 receipt
//                     → POST /api/payments/iap/google/verify with productId+token
```
(Full patch already scaffolded in `BillingScreen.js` — search for `TODO: IAP`.)

---

## 3. Verifying the wiring after products are created

Once at least one sandbox purchase succeeds, look for the receipt in Mongo:
```bash
mongosh iema_ai_v2 --eval "db.iap_receipts.find({}).sort({created_at:-1}).limit(5)"
```
And check `subscriptions` collection for the corresponding `status: active`
entry linked to your user_id.

---

## 4. Razorpay LIVE — smoke test

Razorpay is now on LIVE keys (`rzp_live_TEZa8OSqIw1nfG`). To confirm end-to-end:
1. Log into the web app as your admin account.
2. Visit `/billing` → click **Subscribe → Pro**.
3. You'll be redirected to `https://rzp.io/rzp/…` — this is a real
   Razorpay-hosted checkout backed by your live merchant.
4. Complete a payment (or cancel — test with the smallest amount).
5. Configure webhook in Razorpay Dashboard:
   - URL: `https://iema-ai-platform.preview.emergentagent.com/api/webhook/razorpay-subscription`
   - Events: `subscription.activated`, `subscription.charged`, `subscription.cancelled`
   - Copy the webhook secret into `RAZORPAY_WEBHOOK_SECRET` in
     `/app/backend/.env` and `sudo supervisorctl restart backend`.
