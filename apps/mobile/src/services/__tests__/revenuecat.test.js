/**
 * Unit tests for src/services/revenuecat.js.
 *
 * react-native-purchases is a native module and cannot run inside Jest, so
 * it is mocked at the module level. `IS_EXPO_GO` and `REVENUECAT_API_KEY`
 * are both computed once at module import time, so each scenario resets the
 * module registry and re-requires a fresh copy of `revenuecat.js`.
 */

describe('services/revenuecat', () => {
  let purchasesMock;
  let revenuecat;

  function setup({
    isExpoGo = false,
    platformOS = 'ios',
    iosKey = 'fake-ios-rc-key',
    androidKey = 'fake-android-rc-key',
  } = {}) {
    jest.resetModules();

    jest.doMock('expo-constants', () => ({
      __esModule: true,
      default: {
        appOwnership: isExpoGo ? 'expo' : null,
        executionEnvironment: isExpoGo ? 'storeClient' : 'standalone',
        expoConfig: {
          extra: {
            revenueCatIosKey: iosKey,
            revenueCatAndroidKey: androidKey,
          },
        },
      },
    }));

    purchasesMock = { configure: jest.fn() };
    jest.doMock('react-native-purchases', () => ({
      __esModule: true,
      default: purchasesMock,
      PURCHASES_ARE_COMPLETED_BY_TYPE: { MY_APP: 'MY_APP', REVENUECAT: 'REVENUECAT' },
      STOREKIT_VERSION: { STOREKIT_1: 1, STOREKIT_2: 2 },
    }));

    // `Platform.select()` in real react-native is resolved from a
    // platform-specific file at bundle/require time (Platform.ios.js /
    // Platform.android.js) — it does not read a mutable `Platform.OS`
    // field dynamically the way plain `Platform.OS === 'android'` checks
    // do. So to deterministically flip which branch `Platform.select()`
    // takes in this test, mock just the `Platform` submodule (not all of
    // `react-native`, which would drag in native-only bits like DevMenu).
    jest.doMock('react-native/Libraries/Utilities/Platform', () => ({
      __esModule: true,
      default: {
        OS: platformOS,
        select: (spec) => (platformOS in spec ? spec[platformOS] : spec.default),
      },
    }));

    revenuecat = require('../revenuecat');
    return revenuecat;
  }

  afterEach(() => {
    jest.dontMock('expo-constants');
    jest.dontMock('react-native-purchases');
    jest.dontMock('react-native/Libraries/Utilities/Platform');
  });

  it('is a no-op inside Expo Go, even with a valid key and userId', () => {
    setup({ isExpoGo: true });

    revenuecat.initRevenueCat('user-123');

    expect(purchasesMock.configure).not.toHaveBeenCalled();
  });

  it('is a no-op when the platform API key is missing', () => {
    // `null`, not `undefined` — an explicit `undefined` would fall through
    // to setup()'s own default parameter value instead of clearing the key.
    setup({ isExpoGo: false, platformOS: 'ios', iosKey: null });

    revenuecat.initRevenueCat('user-123');

    expect(purchasesMock.configure).not.toHaveBeenCalled();
  });

  it('is a no-op when no userId is supplied', () => {
    setup({ isExpoGo: false });

    revenuecat.initRevenueCat(undefined);

    expect(purchasesMock.configure).not.toHaveBeenCalled();
  });

  it('configures Purchases with the observer-mode shape on iOS', () => {
    setup({ isExpoGo: false, platformOS: 'ios', iosKey: 'ios-key-1' });

    revenuecat.initRevenueCat('user-abc');

    expect(purchasesMock.configure).toHaveBeenCalledTimes(1);
    expect(purchasesMock.configure).toHaveBeenCalledWith({
      apiKey: 'ios-key-1',
      appUserID: 'user-abc',
      purchasesAreCompletedBy: {
        type: 'MY_APP',
        storeKitVersion: 2,
      },
    });
  });

  it('configures Purchases with the platform-selected key on Android', () => {
    setup({ isExpoGo: false, platformOS: 'android', androidKey: 'android-key-1' });

    revenuecat.initRevenueCat('user-xyz');

    expect(purchasesMock.configure).toHaveBeenCalledWith({
      apiKey: 'android-key-1',
      appUserID: 'user-xyz',
      purchasesAreCompletedBy: {
        type: 'MY_APP',
        storeKitVersion: 2,
      },
    });
  });

  it('only configures once even if called multiple times', () => {
    setup({ isExpoGo: false, platformOS: 'ios' });

    revenuecat.initRevenueCat('user-1');
    revenuecat.initRevenueCat('user-1');
    revenuecat.initRevenueCat('user-2');

    expect(purchasesMock.configure).toHaveBeenCalledTimes(1);
  });
});
