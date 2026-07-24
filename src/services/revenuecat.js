/**
 * RevenueCat — Observer Mode.
 *
 * The app already owns its purchase flow (see `iap.js`: expo-iap ->
 * `/payments/iap/apple/verify` -> credits). This module only makes
 * RevenueCat *observe* the StoreKit transactions expo-iap already makes,
 * via `purchasesAreCompletedBy: MY_APP` — it does not take over checkout,
 * and does not affect the existing verify/credit flow.
 *
 * iOS only for now. Android's RevenueCat app exists in the dashboard but
 * isn't wired up here yet.
 */
import { Platform } from 'react-native';
import Constants from 'expo-constants';

const IS_EXPO_GO =
  Constants?.appOwnership === 'expo' ||
  Constants?.executionEnvironment === 'storeClient';

const REVENUECAT_IOS_API_KEY = 'appl_jFQKLAUZpcGOOLtuiKpFLQKRMNp';

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
  if (_configured || Platform.OS !== 'ios' || !userId) return;
  const Purchases = loadPurchases();
  if (!Purchases) return; // Expo Go / module unavailable

  const { PURCHASES_ARE_COMPLETED_BY_TYPE, STOREKIT_VERSION } = require('react-native-purchases');
  Purchases.configure({
    apiKey: REVENUECAT_IOS_API_KEY,
    appUserID: userId,
    purchasesAreCompletedBy: {
      type: PURCHASES_ARE_COMPLETED_BY_TYPE.MY_APP,
      storeKitVersion: STOREKIT_VERSION.STOREKIT_2,
    },
  });
  _configured = true;
}
