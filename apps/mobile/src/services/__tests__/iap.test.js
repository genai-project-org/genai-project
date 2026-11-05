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

  // Product ids come from the backend (GET /api/pricing), not from the client
  // ---------------------------------------------------------------------
  describe('product catalogue', () => {
    it('has no hardcoded plan/product mapping: ids are served by the backend', () => {
      setup();
      expect(iap.PRODUCT_TO_PLAN).toBeUndefined();
      expect(typeof iap.loadProducts).toBe('function');
      expect(typeof iap.purchaseProduct).toBe('function');
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

    it('purchaseProduct() rejects with a helpful message in Expo Go', async () => {
      setup({ isExpoGo: true });
      await expect(iap.purchaseProduct('iema.pack.surge')).rejects.toThrow(
        /Expo Go/
      );
    });

    it('initIap() reports unavailable in Expo Go without touching expo-iap', async () => {
      setup({ isExpoGo: true });
      const result = await iap.initIap();
      expect(result).toEqual({ ok: false, reason: expect.stringContaining('Expo Go') });
    });
  });

  // purchaseProduct(): iOS vs Android request shaping (consumable credit packs)
  // ---------------------------------------------------------------------
  describe('purchaseProduct() request shape', () => {
    it('iOS: sends { ios: { sku, quantity: 1 } } as an in-app product', async () => {
      setup({ isExpoGo: false, platformOS: 'ios' });

      await iap.purchaseProduct('iema.pack.surge');

      expect(expoIapMock.requestPurchase).toHaveBeenCalledWith({
        request: { ios: { sku: 'iema.pack.surge', quantity: 1 } },
        type: 'in-app',
      });
    });

    it('Android: sends { android: { skus } } as an in-app product, no subscription offers', async () => {
      setup({ isExpoGo: false, platformOS: 'android' });

      await iap.purchaseProduct('iema.pack.surge');

      expect(expoIapMock.requestPurchase).toHaveBeenCalledWith({
        request: { android: { skus: ['iema.pack.surge'] } },
        type: 'in-app',
      });
    });

    it('loadProducts() fetches the given skus as in-app products', async () => {
      setup({ isExpoGo: false, platformOS: 'android' });
      expoIapMock.fetchProducts.mockResolvedValue([{ id: 'iema.pack.surge' }]);

      const products = await iap.loadProducts(['iema.pack.surge']);

      expect(expoIapMock.fetchProducts).toHaveBeenCalledWith({ skus: ['iema.pack.surge'], type: 'in-app' });
      expect(products).toEqual([{ id: 'iema.pack.surge' }]);
    });

    it('loadProducts() returns [] without calling the store when there are no skus', async () => {
      setup({ isExpoGo: false, platformOS: 'ios' });
      expect(await iap.loadProducts([])).toEqual([]);
      expect(expoIapMock.fetchProducts).not.toHaveBeenCalled();
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

      const purchase = { productId: 'iema.pack.surge', purchaseToken: 'jws-token-not-used' };
      await handlePurchase(purchase);

      expect(expoIapMock.getReceiptDataIOS).toHaveBeenCalled();
      expect(apiMock.post).toHaveBeenCalledWith('/payments/iap/apple/verify', {
        receipt: 'base64-receipt-blob',
      });
      expect(expoIapMock.finishTransaction).toHaveBeenCalledWith({
        purchase,
        isConsumable: true,
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

      await handlePurchase({ productId: 'iema.pack.surge', purchaseToken: 'x' });

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

      const purchase = { productId: 'iema.pack.turbo', purchaseToken: 'android-token-xyz' };
      await handlePurchase(purchase);

      expect(expoIapMock.getReceiptDataIOS).not.toHaveBeenCalled();
      expect(apiMock.post).toHaveBeenCalledWith('/payments/iap/google/verify', {
        product_id: 'iema.pack.turbo',
        purchase_token: 'android-token-xyz',
        is_subscription: false,
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

      await handlePurchase({ productId: 'iema.pack.turbo', purchaseToken: 'reused-token' });

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
