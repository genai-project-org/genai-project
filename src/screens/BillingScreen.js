import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, ScrollView, Alert, ActivityIndicator, Platform } from 'react-native';
import { useSelector } from 'react-redux';
import * as WebBrowser from 'expo-web-browser';
import { Check } from 'lucide-react-native';
import api from '../api';
import ScreenHeader from '../components/ScreenHeader';
import { Button } from '../components/UI';
import { colors, spacing, fontSize, radii } from '../theme';
import {
  isIapAvailable, initIap, loadSubscriptions, purchaseSubscription, endIap,
  PRODUCT_TO_PLAN,
} from '../services/iap';
import { initRevenueCat } from '../services/revenuecat';

/**
 * Billing screen — uses native IAP for iOS + Android subscriptions
 * (Apple StoreKit / Google Play Billing) as required by App Store 3.1.1 and
 * Google Play Billing policy. Falls back to Razorpay Payment Links for the
 * one-time top-up packs (still permitted because they map to a real,
 * off-platform account balance, not to unlocking in-app content).
 *
 * When running under Expo Go the `expo-iap` native module is not
 * linked; we detect that and hide the IAP buttons behind an informational
 * card instead of crashing.
 */
export default function BillingScreen({ navigation }) {
  const userId = useSelector((s) => s.auth.user?.id);
  const [packs, setPacks] = useState([]);
  const [plans, setPlans] = useState([]);
  const [iapProducts, setIapProducts] = useState([]);
  const [iapReady, setIapReady] = useState(false);
  const [buying, setBuying] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [packsRes, plansRes] = await Promise.allSettled([
        api.get('/packs/?currency=usd'),
        api.get('/payments/plans'),
      ]);
      if (packsRes.status === 'fulfilled') setPacks(packsRes.value.data.items || []);
      if (plansRes.status === 'fulfilled') {
        setPlans(plansRes.value.data.items || []);
      }
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Initialise IAP once we know which plans exist.
  useEffect(() => {
    let mounted = true;
    (async () => {
      if (!isIapAvailable()) return; // Expo Go — skip silently
      initRevenueCat(userId); // Observer Mode: track transactions expo-iap makes, no checkout changes.
      const res = await initIap({
        onPurchase: (verified) => {
          Alert.alert('Subscription active',
            `Your ${verified.plan_id?.toUpperCase()} plan is now active. Enjoy your credits!`);
          navigation.navigate('Wallet');
          setBuying(null);
        },
        onError: (err) => {
          Alert.alert('Purchase failed', err?.message || String(err));
          setBuying(null);
        },
      });
      if (!mounted) return;
      if (res?.ok) {
        setIapReady(true);
        const products = await loadSubscriptions();
        if (mounted) setIapProducts(products);
      }
    })();
    return () => { mounted = false; endIap(); };
  }, [navigation]);

  const openHostedCheckout = async (shortUrl, onSettled) => {
    try {
      const result = await WebBrowser.openBrowserAsync(shortUrl, {
        dismissButtonStyle: 'close',
        controlsColor: colors.primary,
      });
      if (result?.type === 'dismiss' || result?.type === 'cancel') {
        await onSettled?.();
      }
    } catch (e) {
      Alert.alert('Checkout error', String(e?.message || e));
    }
  };

  /** Top-up packs — off-platform balance, Razorpay Payment Link. */
  const buyPack = async (pack) => {
    setBuying(pack.slug);
    try {
      const { data } = await api.post('/payments/razorpay/order', { pack_slug: pack.slug });
      if (!data?.short_url) throw new Error('No checkout URL returned');
      await openHostedCheckout(data.short_url, async () => {
        try {
          const { data: st } = await api.get(`/payments/razorpay/link-status/${data.payment_link_id}`);
          if (st.status === 'paid') {
            Alert.alert('Payment successful', `${Math.floor(st.credits)} credits added.`);
            navigation.navigate('Wallet');
          } else if (st.status === 'cancelled' || st.status === 'expired') {
            Alert.alert('Payment not completed', 'The checkout was cancelled or expired.');
          } else {
            Alert.alert('Payment pending', 'Your credits will appear shortly.');
          }
        } catch {
          Alert.alert('Verification pending', 'Please check the Wallet screen shortly.');
        }
      });
    } catch (err) {
      Alert.alert('Payment failed', err.response?.data?.detail || err.message || 'Try again');
    } finally { setBuying(null); }
  };

  /** Subscription — native IAP via Apple StoreKit / Google Play Billing. */
  const subscribeIap = async (plan) => {
    const sku = Object.entries(PRODUCT_TO_PLAN).find(([, planId]) => planId === plan.plan_id)?.[0];
    if (!sku) {
      Alert.alert('Product unavailable', `No store product mapped for plan "${plan.plan_id}".`);
      return;
    }
    if (!isIapAvailable()) {
      Alert.alert(
        'IAP unavailable',
        'In-app purchases are only available in a native build. Install the IEMA.ai app from TestFlight / Play Store.',
      );
      return;
    }
    if (!iapReady) {
      Alert.alert('Please wait', 'Store is still connecting…');
      return;
    }
    const known = iapProducts.some((p) => p.productId === sku);
    if (!known) {
      Alert.alert(
        'Product not found',
        `The store didn't return "${sku}". Make sure the product is created and active in ${Platform.OS === 'ios' ? 'App Store Connect' : 'Google Play Console'} and that this build is on the same test track.`,
      );
      return;
    }
    setBuying(plan.plan_id);
    try {
      await purchaseSubscription(sku);
      // Success is delivered through the purchaseUpdatedListener → onPurchase.
    } catch (err) {
      if (err?.code !== 'E_USER_CANCELLED') {
        Alert.alert('Purchase failed', err?.message || String(err));
      }
      setBuying(null);
    }
  };

  if (loading) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.bg }}>
        <ScreenHeader title="Billing" navigation={navigation} />
        <ActivityIndicator color={colors.primary} style={{ marginTop: 40 }} />
      </View>
    );
  }

  const iapNotAvailable = !isIapAvailable();

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }}>
      <ScreenHeader title="Billing" navigation={navigation} />
      <ScrollView contentContainerStyle={{ padding: spacing.md, gap: spacing.md }}>
        <Text style={{ color: colors.textMuted, fontSize: fontSize.sm }}>
          {`Prices in USD. Subscriptions are billed by ${Platform.OS === 'ios' ? 'Apple' : 'Google Play'}. Top-up packs bill via Razorpay.`}
        </Text>

        {iapNotAvailable && (
          <View style={{ borderWidth: 1, borderColor: colors.border, borderRadius: radii.md, padding: spacing.md, backgroundColor: colors.card }}>
            <Text style={{ color: colors.text, fontWeight: '600' }}>Store not linked</Text>
            <Text style={{ color: colors.textMuted, fontSize: fontSize.sm, marginTop: 4 }}>
              You are running IEMA.ai in Expo Go, which doesn&#39;t include the native In-App
              Purchase module. Subscriptions become available once you install a native build
              from TestFlight (iOS) or the internal test track (Android).
            </Text>
          </View>
        )}

        {plans.length > 0 && (
          <>
            <Text style={{ color: colors.text, fontSize: fontSize.lg, fontWeight: '600', marginTop: 8 }}>
              Recurring plans
            </Text>
            {plans.map((p) => {
              const sku = Object.entries(PRODUCT_TO_PLAN).find(([, id]) => id === p.plan_id)?.[0];
              const storeProduct = iapProducts.find((sp) => sp.productId === sku);
              const priceLabel = storeProduct
                ? (storeProduct.localizedPrice
                    || storeProduct.subscriptionOfferDetails?.[0]?.pricingPhases
                        ?.pricingPhaseList?.[0]?.formattedPrice
                    || `$${p.price_usd}`)
                : `$${p.price_usd}`;
              return (
                <View key={p.plan_id} style={cardStyle(false)}>
                  <Text style={labelStyle}>{(p.billing_period || 'monthly').toUpperCase()}</Text>
                  <Text style={{ color: colors.text, fontSize: fontSize.lg, fontWeight: '600', marginTop: 2 }}>
                    {p.name}
                  </Text>
                  <Text style={priceStyle}>
                    {priceLabel}
                    <Text style={{ color: colors.textMuted, fontSize: fontSize.sm, fontWeight: '400' }}>
                      {' '}/ {p.billing_period === 'annual' ? 'year' : 'month'}
                    </Text>
                  </Text>
                  <View style={{ gap: 4, marginTop: 12 }}>
                    <Row text={`${p.monthly_credits} credits / ${p.billing_period === 'annual' ? 'year' : 'month'}`} />
                    <Row text={`${p.window_credits} credits per ${p.window_hours}h window`} />
                    <Row text="All AI modules" />
                  </View>
                  <Button title={buying === p.plan_id ? 'Purchasing\u2026' : `Subscribe`}
                          loading={buying === p.plan_id}
                          onPress={() => subscribeIap(p)}
                          style={{ marginTop: spacing.lg }} />
                </View>
              );
            })}
          </>
        )}

        <Text style={{ color: colors.text, fontSize: fontSize.lg, fontWeight: '600', marginTop: 16 }}>
          Top-up packs
        </Text>
        {packs.map((p) => (
          <View key={p.slug} style={cardStyle(p.is_popular)}>
            {p.is_popular && (
              <View style={{ position: 'absolute', top: -10, right: 14, backgroundColor: colors.primary, borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2 }}>
                <Text style={{ color: '#fff', fontSize: 10, textTransform: 'uppercase', letterSpacing: 1, fontWeight: '600' }}>Popular</Text>
              </View>
            )}
            <Text style={{ color: colors.textMuted, fontSize: fontSize.sm }}>{p.name}</Text>
            <Text style={priceStyle}>${p.price.toFixed(2)}</Text>
            <Text style={{ color: colors.textMuted, marginTop: 2 }}>
              {Math.floor(p.credits).toLocaleString()} credits
              {p.bonus_credits > 0 && (
                <Text style={{ color: colors.success }}> + {Math.floor(p.bonus_credits)} bonus</Text>
              )}
            </Text>
            <View style={{ gap: 4, marginTop: 16 }}>
              <Row text="Never-expiring credits" />
              <Row text="All models: Claude + GPT" />
              <Row text="Priority processing" />
            </View>
            <Button title={`Buy ${p.name}`} loading={buying === p.slug} onPress={() => buyPack(p)}
                    variant={p.is_popular ? 'primary' : 'outline'} style={{ marginTop: spacing.lg }} />
          </View>
        ))}
      </ScrollView>
    </View>
  );
}

function Row({ text }) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
      <Check color={colors.primary} size={14} />
      <Text style={{ color: colors.textMuted, fontSize: fontSize.sm }}>{text}</Text>
    </View>
  );
}

const cardStyle = (popular) => ({
  borderWidth: 1,
  borderColor: popular ? colors.primary : colors.border,
  borderRadius: radii.lg,
  backgroundColor: colors.card,
  padding: spacing.lg,
  position: 'relative',
});
const priceStyle = { color: colors.text, fontSize: 32, fontWeight: '600', letterSpacing: -1, marginTop: 4 };
const labelStyle = { color: colors.primary, fontSize: 10, letterSpacing: 1, fontWeight: '600' };
