/**
 * Unit tests for src/services/iap.js.
 *
 * expo-iap is a native module and cannot run inside Jest (no real
 * StoreKit/Play Billing), so it is mocked at the module level. We only
 * exercise the JS logic around it: product/plan mapping, Expo Go detection,
 * iOS vs Android request shaping, and the iOS vs Android verify branching.
 *
 * `IS_EXPO_GO` and `REVENUECAT_API_KEY`-style constants in this codebase are
 * computed once at module import time from `expo-constants`, so each test
 * that needs a different Expo Go / platform scenario resets the module
 * registry and re-requires a fresh copy of `iap.js` with fresh mocks.
 */

describe('services/iap', () => {
  let Platform;
  let apiMock;
  let expoIapMock;
  let iap;

  /**
   * Rebuilds mocks and re-requires a fresh `iap.js` module instance so
   * module-level state (`IS_EXPO_GO`, `_initialized`, `_subscriptions`, ...)
   * doesn't leak between test cases.
   */
  function setup({ isExpoGo = false, platformOS = 'ios' } = {}) {
    jest.resetModules();

    jest.doMock('expo-constants', () => ({
      __esModule: true,
      default: {
        appOwnership: isExpoGo ? 'expo' : null,
        executionEnvironment: isExpoGo ? 'storeClient' : 'standalone',
        expoConfig: { extra: {} },
      },
    }));

    apiMock = { post: jest.fn() };
    jest.doMock('../../api', () => ({ __esModule: true, default: apiMock }));

    expoIapMock = {
      initConnection: jest.fn().mockResolvedValue(undefined),
      purchaseUpdatedListener: jest.fn(),
      purchaseErrorListener: jest.fn(),
      fetchProducts: jest.fn().mockResolvedValue([]),
      requestPurchase: jest.fn().mockResolvedValue({}),
      getReceiptDataIOS: jest.fn().mockResolvedValue('base64-receipt-blob'),
      finishTransaction: jest.fn().mockResolvedValue(undefined),
      endConnection: jest.fn().mockResolvedValue(undefined),
    };
    if (!isExpoGo) {
      jest.doMock('expo-iap', () => expoIapMock);
    }

    Platform = require('react-native').Platform;
    Platform.OS = platformOS;

    iap = require('../iap');
    return iap;
  }

  afterEach(() => {
    jest.dontMock('expo-constants');
    jest.dontMock('../../api');
    jest.dontMock('expo-iap');
  });

  // ---------------------------------------------------------------------
  // PRODUCT_TO_PLAN mapping
  // ---------------------------------------------------------------------
  describe('PRODUCT_TO_PLAN', () => {
    it('maps every known store product id to the expected backend plan', () => {
      setup();
      expect(iap.PRODUCT_TO_PLAN).toEqual({
        'iema.pro.monthly': 'pro',
        'iema.pro.annual': 'pro_annual',
        'iema.team.monthly': 'team',
        'iema.team.annual': 'team_annual',
      });
    });
  });

  // ---------------------------------------------------------------------
  // Expo Go detection / availability
  // ---------------------------------------------------------------------
  describe('Expo Go detection', () => {
    it('isIapAvailable() is false when running inside Expo Go', () => {
      setup({ isExpoGo: true });
      expect(iap.isIapAvailable()).toBe(false);
    });

    it('isIapAvailable() is true outside Expo Go when expo-iap is present', () => {
      setup({ isExpoGo: false });
      expect(iap.isIapAvailable()).toBe(true);
    });

    it('purchaseSubscription() rejects with a helpful message in Expo Go', async () => {
      setup({ isExpoGo: true });
      await expect(iap.purchaseSubscription('iema.pro.monthly')).rejects.toThrow(
        /Expo Go/
      );
    });

    it('initIap() reports unavailable in Expo Go without touching expo-iap', async () => {
      setup({ isExpoGo: true });
      const result = await iap.initIap();
      expect(result).toEqual({ ok: false, reason: expect.stringContaining('Expo Go') });
    });
  });

  // ---------------------------------------------------------------------
  // purchaseSubscription(): iOS vs Android request shaping
  // ---------------------------------------------------------------------
  describe('purchaseSubscription() request shape', () => {
    it('iOS: sends only { ios: { sku } }, no offer/token logic', async () => {
      setup({ isExpoGo: false, platformOS: 'ios' });

      await iap.purchaseSubscription('iema.pro.monthly');

      expect(expoIapMock.requestPurchase).toHaveBeenCalledWith({
        request: { ios: { sku: 'iema.pro.monthly' } },
        type: 'subs',
        willAutoRenew: true,
      });
    });

    it('Android: sends { skus } with no subscriptionOffers when no offerToken is known', async () => {
      setup({ isExpoGo: false, platformOS: 'android' });
      expoIapMock.fetchProducts.mockResolvedValue([
        { id: 'iema.pro.monthly', productId: 'iema.pro.monthly' },
      ]);
      await iap.loadSubscriptions();

      await iap.purchaseSubscription('iema.pro.monthly');

      expect(expoIapMock.requestPurchase).toHaveBeenCalledWith({
        request: { android: { skus: ['iema.pro.monthly'] } },
        type: 'subs',
        willAutoRenew: true,
      });
    });

    it('Android: extracts and includes the base-plan offerToken when present', async () => {
      setup({ isExpoGo: false, platformOS: 'android' });
      expoIapMock.fetchProducts.mockResolvedValue([
        {
          id: 'iema.pro.monthly',
          productId: 'iema.pro.monthly',
          subscriptionOfferDetailsAndroid: [{ offerToken: 'OFFER_TOKEN_ABC' }],
        },
      ]);
      await iap.loadSubscriptions();

      await iap.purchaseSubscription('iema.pro.monthly');

      expect(expoIapMock.requestPurchase).toHaveBeenCalledWith({
        request: {
          android: {
            skus: ['iema.pro.monthly'],
            subscriptionOffers: [{ offerToken: 'OFFER_TOKEN_ABC' }],
          },
        },
        type: 'subs',
        willAutoRenew: true,
      });
    });

    it('Android: matches the product by productId as well as id', async () => {
      setup({ isExpoGo: false, platformOS: 'android' });
      expoIapMock.fetchProducts.mockResolvedValue([
        {
          // no `id` field, only `productId` — code falls back to it
          productId: 'iema.team.annual',
          subscriptionOfferDetailsAndroid: [{ offerToken: 'TEAM_OFFER' }],
        },
      ]);
      await iap.loadSubscriptions();

      await iap.purchaseSubscription('iema.team.annual');

      expect(expoIapMock.requestPurchase).toHaveBeenCalledWith(
        expect.objectContaining({
          request: {
            android: {
              skus: ['iema.team.annual'],
              subscriptionOffers: [{ offerToken: 'TEAM_OFFER' }],
            },
          },
        })
      );
    });
  });

  // ---------------------------------------------------------------------
  // verifyPurchase() (private — exercised via the purchaseUpdatedListener
  // callback registered by initIap(), which is the only way it's invoked).
  // ---------------------------------------------------------------------
  describe('verify purchase branching (via initIap purchase listener)', () => {
    async function initAndCapturePurchaseHandler({ onPurchase, onError } = {}) {
      await iap.initIap({ onPurchase, onError });
      expect(expoIapMock.purchaseUpdatedListener).toHaveBeenCalledTimes(1);
      return expoIapMock.purchaseUpdatedListener.mock.calls[0][0];
    }

    it('iOS: reads the legacy receipt blob and posts to the apple verify endpoint', async () => {
      setup({ isExpoGo: false, platformOS: 'ios' });
      apiMock.post.mockResolvedValue({ data: { ok: true, credits: 500 } });
      const onPurchase = jest.fn();
      const onError = jest.fn();
      const handlePurchase = await initAndCapturePurchaseHandler({ onPurchase, onError });

      const purchase = { productId: 'iema.pro.monthly', purchaseToken: 'jws-token-not-used' };
      await handlePurchase(purchase);

      expect(expoIapMock.getReceiptDataIOS).toHaveBeenCalled();
      expect(apiMock.post).toHaveBeenCalledWith('/payments/iap/apple/verify', {
        receipt: 'base64-receipt-blob',
      });
      expect(expoIapMock.finishTransaction).toHaveBeenCalledWith({
        purchase,
        isConsumable: false,
      });
      expect(onPurchase).toHaveBeenCalledWith({ ok: true, credits: 500 }, purchase);
      expect(onError).not.toHaveBeenCalled();
    });

    it('iOS: surfaces an error and never calls the backend when no receipt is available', async () => {
      setup({ isExpoGo: false, platformOS: 'ios' });
      expoIapMock.getReceiptDataIOS.mockResolvedValue(undefined);
      const onPurchase = jest.fn();
      const onError = jest.fn();
      const handlePurchase = await initAndCapturePurchaseHandler({ onPurchase, onError });

      await handlePurchase({ productId: 'iema.pro.monthly', purchaseToken: 'x' });

      expect(apiMock.post).not.toHaveBeenCalled();
      expect(onPurchase).not.toHaveBeenCalled();
      expect(onError).toHaveBeenCalledWith(expect.any(Error));
      expect(onError.mock.calls[0][0].message).toMatch(/no iOS receipt/);
    });

    it('Android: posts purchaseToken/productId to the google verify endpoint', async () => {
      setup({ isExpoGo: false, platformOS: 'android' });
      apiMock.post.mockResolvedValue({ data: { ok: true, credits: 250 } });
      const onPurchase = jest.fn();
      const onError = jest.fn();
      const handlePurchase = await initAndCapturePurchaseHandler({ onPurchase, onError });

      const purchase = { productId: 'iema.team.monthly', purchaseToken: 'android-token-xyz' };
      await handlePurchase(purchase);

      expect(expoIapMock.getReceiptDataIOS).not.toHaveBeenCalled();
      expect(apiMock.post).toHaveBeenCalledWith('/payments/iap/google/verify', {
        product_id: 'iema.team.monthly',
        purchase_token: 'android-token-xyz',
        is_subscription: true,
      });
      expect(onPurchase).toHaveBeenCalledWith({ ok: true, credits: 250 }, purchase);
      expect(onError).not.toHaveBeenCalled();
    });

    it('Android: a server rejection routes to onError instead of onPurchase', async () => {
      setup({ isExpoGo: false, platformOS: 'android' });
      apiMock.post.mockResolvedValue({ data: { ok: false, error: 'receipt already used' } });
      const onPurchase = jest.fn();
      const onError = jest.fn();
      const handlePurchase = await initAndCapturePurchaseHandler({ onPurchase, onError });

      await handlePurchase({ productId: 'iema.team.monthly', purchaseToken: 'reused-token' });

      expect(onPurchase).not.toHaveBeenCalled();
      expect(expoIapMock.finishTransaction).not.toHaveBeenCalled();
      expect(onError).toHaveBeenCalledWith(expect.any(Error));
      expect(onError.mock.calls[0][0].message).toBe('receipt already used');
    });
  });

  // ---------------------------------------------------------------------
  // endIap() teardown
  // ---------------------------------------------------------------------
  describe('endIap()', () => {
    it('removes listeners and ends the native connection once initialized', async () => {
      setup({ isExpoGo: false, platformOS: 'ios' });
      const removeUpdate = jest.fn();
      const removeError = jest.fn();
      expoIapMock.purchaseUpdatedListener.mockReturnValue({ remove: removeUpdate });
      expoIapMock.purchaseErrorListener.mockReturnValue({ remove: removeError });

      await iap.initIap();
      await iap.endIap();

      expect(removeUpdate).toHaveBeenCalled();
      expect(removeError).toHaveBeenCalled();
      expect(expoIapMock.endConnection).toHaveBeenCalled();
    });

    it('is a no-op when never initialized', async () => {
      setup({ isExpoGo: false, platformOS: 'ios' });
      await expect(iap.endIap()).resolves.toBeUndefined();
      expect(expoIapMock.endConnection).not.toHaveBeenCalled();
    });
  });
});
