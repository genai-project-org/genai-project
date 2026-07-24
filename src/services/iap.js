/**
 * IAP bridge — uses **expo-iap@~3.0.0** (Expo Module, StoreKit 2 on iOS +
 * Google Play Billing v6 on Android). API is provider-agnostic so the rest
 * of the app (BillingScreen, backend receipt endpoints) is unchanged.
 *
 *  - iOS   → Apple StoreKit 2   (receipt POST → /api/payments/iap/apple/verify)
 *  - Android → Google Play Billing (POST → /api/payments/iap/google/verify)
 *  - Expo Go / web → module unavailable; caller shows a graceful fallback UI.
 */
import { Platform } from 'react-native';
import Constants from 'expo-constants';
import api from '../api';

// expo-iap still requires native code, so it cannot run inside Expo Go.
const IS_EXPO_GO =
  Constants?.appOwnership === 'expo' ||
  Constants?.executionEnvironment === 'storeClient';

const SUB_PRODUCT_IDS = [
  'iema.pro.monthly',
  'iema.pro.annual',
  'iema.team.monthly',
  'iema.team.annual',
];

// Must stay in sync with backend `services/payments_service.py`
// DEFAULT_PRODUCT_MAP.
export const PRODUCT_TO_PLAN = {
  'iema.pro.monthly': 'pro',
  'iema.pro.annual': 'pro_annual',
  'iema.team.monthly': 'team',
  'iema.team.annual': 'team_annual',
};

let _iap = null;
let _initialized = false;
let _subscriptions = [];
let _purchaseUpdateSub = null;
let _purchaseErrorSub = null;

function loadIap() {
  if (IS_EXPO_GO) return null;
  if (_iap) return _iap;
  try {
    // eslint-disable-next-line global-require
    _iap = require('expo-iap');
    return _iap;
  } catch {
    return null;
  }
}

export function isIapAvailable() {
  return !!loadIap();
}

export async function initIap({ onPurchase, onError } = {}) {
  const iap = loadIap();
  // console.log(iap);
  
  if (!iap) return { ok: false, reason: 'expo-iap unavailable (Expo Go or web)' };
  if (_initialized) return { ok: true, cached: true };
  try {
    await iap.initConnection();
    _purchaseUpdateSub = iap.purchaseUpdatedListener(async (purchase) => {
      try {
        const verified = await verifyPurchase(purchase);
        if (verified?.ok) {
          try {
            await iap.finishTransaction({ purchase, isConsumable: false });
          } catch { /* already finished */ }
          onPurchase?.(verified, purchase);
        } else {
          onError?.(new Error(verified?.error || 'Server rejected receipt'));
        }
      } catch (e) {
        onError?.(e);
      }
    });
    _purchaseErrorSub = iap.purchaseErrorListener((err) => {
      if (err?.code !== 'E_USER_CANCELLED') onError?.(err);
    });
    _initialized = true;
    return { ok: true };
  } catch (e) {
    return { ok: false, reason: e?.message || String(e) };
  }
}

export async function loadSubscriptions() {
  const iap = loadIap();
  if (!iap) return [];
  try {
    _subscriptions = await iap.getSubscriptions({ skus: SUB_PRODUCT_IDS });
    return _subscriptions;
  } catch {
    return [];
  }
}

export async function purchaseSubscription(sku) {
  const iap = loadIap();
  if (!iap) throw new Error('In-app purchases are unavailable in Expo Go. Use a native / EAS build.');
  if (!_initialized) await initIap();

  if (Platform.OS === 'android') {
    // Google Play Billing v6+ requires the base-plan offerToken.
    const product = _subscriptions.find((p) => p.productId === sku || p.id === sku);
    const offerToken = product?.subscriptionOfferDetails?.[0]?.offerToken;
    return iap.requestPurchase({
      request: {
        android: {
          skus: [sku],
          ...(offerToken
            ? { subscriptionOffers: [{ sku, offerToken }] }
            : {}),
        },
      },
      type: 'subs',
    });
  }

  // iOS StoreKit 2 — sku only.
  return iap.requestPurchase({
    request: { ios: { sku } },
    type: 'subs',
  });
}

async function verifyPurchase(purchase) {
  if (Platform.OS === 'ios') {
    // StoreKit 2 exposes a JWS receipt on `jwsRepresentation`; expo-iap also
    // maps the classic App Store receipt to `transactionReceipt`. We send
    // whichever is present.
    const receipt = purchase?.jwsRepresentation || purchase?.transactionReceipt;
    if (!receipt) return { ok: false, error: 'no iOS receipt' };
    const { data } = await api.post('/payments/iap/apple/verify', { receipt });
    return data;
  }
  const { data } = await api.post('/payments/iap/google/verify', {
    product_id: purchase.productId,
    purchase_token: purchase.purchaseToken,
    is_subscription: true,
  });
  return data;
}

export async function endIap() {
  const iap = loadIap();
  if (!iap || !_initialized) return;
  try { _purchaseUpdateSub?.remove?.(); } catch { /* ignore */ }
  try { _purchaseErrorSub?.remove?.(); } catch { /* ignore */ }
  try { await iap.endConnection(); } catch { /* ignore */ }
  _initialized = false;
  _purchaseUpdateSub = null;
  _purchaseErrorSub = null;
}
