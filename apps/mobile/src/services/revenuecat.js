/**
 * RevenueCat — Observer Mode.
 *
 * The app already owns its purchase flow (see `iap.js`: expo-iap ->
 * `/payments/iap/{apple,google}/verify` -> credits). This module only makes
 * RevenueCat *observe* the StoreKit/Play Billing transactions expo-iap
 * already makes, via `purchasesAreCompletedBy: MY_APP` — it does not take
 * over checkout, and does not affect the existing verify/credit flow.
 *
 * `storeKitVersion` is iOS-only and ignored by the SDK on Android, so the
 * same purchasesAreCompletedBy config is shared across both platforms.
 */
import { Platform } from 'react-native';
import Constants from 'expo-constants';

const IS_EXPO_GO =
  Constants?.appOwnership === 'expo' ||
  Constants?.executionEnvironment === 'storeClient';

const REVENUECAT_API_KEY = Platform.select({
  ios: Constants.expoConfig?.extra?.revenueCatIosKey,
  android: Constants.expoConfig?.extra?.revenueCatAndroidKey,
});

let _configured = false;

function loadPurchases() {
  if (IS_EXPO_GO) return null;
  try {
    // eslint-disable-next-line global-require
    return require('react-native-purchases').default;
  } catch {
    return null;
  }
}

/**
 * @param {string} userId - our Mongo user `_id` string. Passed as RevenueCat's
 * `appUserID` so the backend webhook's `app_user_id` equals `user.id` directly
 * (no lookup table needed) — see services/payments_service.py handle_revenuecat_webhook.
 */
export function initRevenueCat(userId) {
  if (_configured || !userId || !REVENUECAT_API_KEY) return;
  const Purchases = loadPurchases();
  if (!Purchases) return; // Expo Go / module unavailable

  const { PURCHASES_ARE_COMPLETED_BY_TYPE, STOREKIT_VERSION } = require('react-native-purchases');
  Purchases.configure({
    apiKey: REVENUECAT_API_KEY,
    appUserID: userId,
    purchasesAreCompletedBy: {
      type: PURCHASES_ARE_COMPLETED_BY_TYPE.MY_APP,
      storeKitVersion: STOREKIT_VERSION.STOREKIT_2,
    },
  });
  _configured = true;
}
