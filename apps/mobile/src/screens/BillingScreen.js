import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, ScrollView, Alert, ActivityIndicator, Platform } from 'react-native';
import { useSelector } from 'react-redux';
import * as WebBrowser from 'expo-web-browser';
import { Check } from 'lucide-react-native';
import api from '../api';
import ScreenHeader from '../components/ScreenHeader';
import { Button, Input } from '../components/UI';
import { colors, spacing, fontSize, radii } from '../theme';
import { isIapAvailable, initIap, loadProducts, purchaseProduct, endIap } from '../services/iap';
import { initRevenueCat } from '../services/revenuecat';

/**
 * Billing screen: two ways to add credits to the one wallet, both priced by the backend
 * (`GET /api/pricing`, nothing hardcoded here):
 *  - Credit packs: consumable in-app purchases (Apple StoreKit / Google Play Billing) using the
 *    product IDs the pricing engine publishes. Where native IAP is unavailable on Android (Expo Go /
 *    dev builds) packs fall back to the hosted Razorpay Payment Link.
 *  - Pay as you go: any amount from the minimum, via a hosted Razorpay Payment Link opened in an
 *    in-app browser. Not offered on iOS (App Store 3.1.1 requires StoreKit for digital goods).
 */
export default function BillingScreen({ navigation }) {
  const userId = useSelector((s) => s.auth.user?.id);
  const [pricing, setPricing] = useState(null);
  const [iapProducts, setIapProducts] = useState([]);
  const [iapReady, setIapReady] = useState(false);
  const [buying, setBuying] = useState(null);
  const [loading, setLoading] = useState(true);
  const [amount, setAmount] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get('/pricing');
      setPricing(data);
      setAmount(String(data.payg?.presets?.[0]?.usd ?? data.payg?.min_usd ?? ''));
    } catch { /* shown as empty state */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!pricing) return undefined;
    let mounted = true;
    (async () => {
      if (!isIapAvailable()) return;
      initRevenueCat(userId);
      const res = await initIap({
        onPurchase: (verified) => {
          Alert.alert('Credits added', `${Math.floor(verified.credits || 0).toLocaleString()} credits are in your wallet.`);
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
        const products = await loadProducts((pricing.store_products || []).map((p) => p.product_id));
        if (mounted) setIapProducts(products);
      }
    })();
    return () => { mounted = false; endIap(); };
  }, [pricing, navigation, userId]);

  const openHostedCheckout = async (data) => {
    if (!data?.short_url) throw new Error('No checkout URL returned');
    const result = await WebBrowser.openBrowserAsync(data.short_url, {
      dismissButtonStyle: 'close',
      controlsColor: colors.primary,
    });
    if (result?.type === 'dismiss' || result?.type === 'cancel') {
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
    }
  };

  const buyPack = async (pack) => {
    setBuying(pack.slug);
    try {
      if (isIapAvailable()) {
        if (!iapReady) { Alert.alert('Please wait', 'Store is still connecting.'); setBuying(null); return; }
        const known = iapProducts.some((p) => p.id === pack.product_id || p.productId === pack.product_id);
        if (!known) {
          Alert.alert('Product not found',
            `The store did not return "${pack.product_id}". Create it in ${Platform.OS === 'ios' ? 'App Store Connect' : 'Google Play Console'} (Admin > Packs & Pricing > export) and use a build on the same test track.`);
          setBuying(null);
          return;
        }
        await purchaseProduct(pack.product_id); // result arrives via the purchase listener
        return;
      }
      if (Platform.OS === 'ios') {
        Alert.alert('Store unavailable', 'In-app purchases need a native TestFlight / App Store build.');
        setBuying(null);
        return;
      }
      const { data } = await api.post('/payments/razorpay/order', { pack_slug: pack.slug });
      await openHostedCheckout(data);
      setBuying(null);
    } catch (err) {
      if (err?.code !== 'E_USER_CANCELLED') {
        Alert.alert('Purchase failed', err.response?.data?.detail || err?.message || 'Try again');
      }
      setBuying(null);
    }
  };

  const payg = pricing?.payg;
  const value = parseFloat(amount);
  const paygValid = payg && Number.isFinite(value) && value >= payg.min_usd && value <= payg.max_usd;
  const paygCredits = paygValid ? Math.floor(value * payg.credits_per_usd) : 0;
  const paygInr = paygValid && pricing.fx_rate
    ? Math.ceil((value * pricing.fx_rate) / pricing.inr_round_step) * pricing.inr_round_step : null;

  const payAsYouGo = async () => {
    if (!paygValid) return;
    setBuying('payg');
    try {
      const { data } = await api.post('/payments/razorpay/payg', { amount_usd: value });
      await openHostedCheckout(data);
    } catch (err) {
      Alert.alert('Payment failed', err.response?.data?.detail || err.message || 'Try again');
    } finally { setBuying(null); }
  };

  if (loading) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.bg }}>
        <ScreenHeader title="Add credits" navigation={navigation} />
        <ActivityIndicator color={colors.primary} style={{ marginTop: 40 }} />
      </View>
    );
  }

  const packs = pricing?.packs || [];
  const storePrice = (p) => {
    const sp = iapProducts.find((x) => x.id === p.product_id || x.productId === p.product_id);
    return sp?.displayPrice || `$${Number(p.price_usd).toFixed(2)}`;
  };
  const renderPack = (p) => (
    <View key={p.slug} style={cardStyle(p.is_popular)}>
      {p.is_popular && (
        <View style={badgeStyle}><Text style={badgeText}>Popular</Text></View>
      )}
      <Text style={{ color: colors.textMuted, fontSize: fontSize.sm }}>{p.name}</Text>
      <Text style={priceStyle}>{storePrice(p)}</Text>
      <Text style={{ color: colors.textMuted, marginTop: 2 }}>
        {Math.floor(p.credits).toLocaleString()} credits
        {p.bonus_credits > 0 && (
          <Text style={{ color: colors.success }}> + {Math.floor(p.bonus_credits).toLocaleString()} bonus</Text>
        )}
      </Text>
      <View style={{ gap: 4, marginTop: 14 }}>
        {!!p.description && <Row text={p.description} />}
        {(p.highlights || []).slice(0, 2).map((h) => (
          <Row key={h.service_key} text={`about ${h.units.toLocaleString()} x ${h.description.toLowerCase()}`} />
        ))}
        <Row text="Never-expiring credits" />
      </View>
      <Button title={`Buy ${p.name}`} loading={buying === p.slug} onPress={() => buyPack(p)}
              variant={p.is_popular ? 'primary' : 'outline'} style={{ marginTop: spacing.lg }} />
    </View>
  );

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }}>
      <ScreenHeader title="Add credits" navigation={navigation} />
      <ScrollView contentContainerStyle={{ padding: spacing.md, gap: spacing.md }} keyboardShouldPersistTaps="handled">
        <Text style={{ color: colors.textMuted, fontSize: fontSize.sm }}>
          One wallet for everything. Credits never expire. No subscription.
        </Text>

        {!pricing && (
          <Text style={{ color: colors.textMuted }}>Could not load pricing. Pull back and try again.</Text>
        )}

        {payg && Platform.OS !== 'ios' && (
          <View style={cardStyle(false)}>
            <Text style={labelStyle}>PAY AS YOU GO</Text>
            <Text style={{ color: colors.text, fontSize: fontSize.lg, fontWeight: '600', marginTop: 2 }}>
              Recharge any amount
            </Text>
            <Text style={{ color: colors.textMuted, fontSize: fontSize.sm, marginTop: 4 }}>
              From ${payg.min_usd}. {payg.credits_per_usd.toLocaleString()} credits per $1.
            </Text>
            <View style={{ flexDirection: 'row', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
              {payg.presets.map((x) => (
                <Button key={x.usd} title={`$${x.usd}`} variant={value === x.usd ? 'primary' : 'outline'}
                        onPress={() => setAmount(String(x.usd))} />
              ))}
            </View>
            <Input value={amount} onChangeText={setAmount} keyboardType="decimal-pad"
                   placeholder={`Amount in USD (min ${payg.min_usd})`} style={{ marginTop: 12 }} />
            {!!amount && !paygValid && (
              <Text style={{ color: colors.danger || '#f59e0b', fontSize: fontSize.sm, marginTop: 6 }}>
                {value < payg.min_usd ? `Minimum recharge is $${payg.min_usd}` : `Maximum recharge is $${payg.max_usd}`}
              </Text>
            )}
            {paygValid && (
              <Text style={{ color: colors.text, marginTop: 10 }}>
                You get {paygCredits.toLocaleString()} credits
                <Text style={{ color: colors.textMuted }}>{paygInr ? `  (about Rs ${paygInr.toLocaleString('en-IN')})` : ''}</Text>
              </Text>
            )}
            <Button title="Recharge" disabled={!paygValid} loading={buying === 'payg'} onPress={payAsYouGo}
                    style={{ marginTop: spacing.md }} />
          </View>
        )}

        <Text style={{ color: colors.text, fontSize: fontSize.lg, fontWeight: '600', marginTop: 8 }}>Credit packs</Text>
        {packs.filter((p) => p.kind !== 'specialised').map(renderPack)}

        {packs.some((p) => p.kind === 'specialised') && (
          <>
            <Text style={{ color: colors.text, fontSize: fontSize.lg, fontWeight: '600', marginTop: 8 }}>Specialised packs</Text>
            {packs.filter((p) => p.kind === 'specialised').map(renderPack)}
          </>
        )}
      </ScrollView>
    </View>
  );
}

function Row({ text }) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
      <Check color={colors.primary} size={14} />
      <Text style={{ color: colors.textMuted, fontSize: fontSize.sm, flexShrink: 1 }}>{text}</Text>
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
const badgeStyle = { position: 'absolute', top: -10, right: 14, backgroundColor: colors.primary, borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2 };
const badgeText = { color: '#fff', fontSize: 10, textTransform: 'uppercase', letterSpacing: 1, fontWeight: '600' };
const priceStyle = { color: colors.text, fontSize: 32, fontWeight: '600', letterSpacing: -1, marginTop: 4 };
const labelStyle = { color: colors.primary, fontSize: 10, letterSpacing: 1, fontWeight: '600' };
