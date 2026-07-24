# IEMA.ai Mobile — React Native (Expo)

Universal Android + iOS app for IEMA.ai, using the same FastAPI backend as web.

- **Bundle ID / Package**: `com.iemaai.app` (matches your live V1)
- **API base URL**: read from `app.json` → `expo.extra.apiBaseUrl`
- **Auth**: JWT (access + refresh), tokens stored in `expo-secure-store`
- **Streaming chat**: SSE via `fetch` + `ReadableStream`
- **Multimodal**: Images picked with `expo-image-picker` → uploaded to backend `/api/uploads/image` → S3 → passed to Claude/GPT vision
- **Theme**: Dark, matching web app (blue `#3b82f6`)

## Screens
- Login, Register, ForgotPassword
- Conversations list, Chat (streaming + image attach)
- Wallet, Usage, Billing, Notifications, Profile, Settings
- Drawer navigation with the same primary + Coming Soon modules as the web sidebar

## Run locally
```bash
cd /app/mobile
yarn install
npx expo start
# scan the QR with Expo Go on iOS/Android, or press i / a for simulators
```

## Build production apps
```bash
# One-time
npm install -g eas-cli
eas login

# Configure once (from repo root)
cd /app/mobile
eas build:configure

# Preview builds
eas build --platform android --profile preview
eas build --platform ios --profile preview

# Store submission (App Store + Play Store)
eas build --platform ios --profile production
eas submit --platform ios
eas build --platform android --profile production
eas submit --platform android
```

## Environment
The API URL is set in `app.json`:
```json
"extra": { "apiBaseUrl": "https://iema-ai-platform.preview.emergentagent.com" }
```
Change to your production API before publishing.

## Notes
- Uses Expo SDK 52 with New Architecture enabled
- Google/Microsoft OAuth in mobile uses `expo-auth-session` (scaffolded to add next)
- Razorpay flow currently opens browser — swap in `react-native-razorpay` SDK for native checkout
- Push notifications: `expo-notifications` — add token registration to `/api/notifications` for real push delivery
