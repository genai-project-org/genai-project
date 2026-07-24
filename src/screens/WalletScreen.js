import React, { useEffect, useState } from 'react';
import { View, Text, ScrollView, RefreshControl } from 'react-native';
import { Wallet as WalletIcon, ArrowUpRight, Gift, Sparkles, Users, ShoppingCart, TrendingDown } from 'lucide-react-native';
import api from '../api';
import ScreenHeader from '../components/ScreenHeader';
import { Card, Button } from '../components/UI';
import { colors, spacing, fontSize, radii } from '../theme';

export default function WalletScreen({ navigation }) {
  const [wallet, setWallet] = useState(null);
  const [txs, setTxs] = useState([]);
  const [refreshing, setRefreshing] = useState(false);

  const load = async () => {
    setRefreshing(true);
    try {
      const [w, t] = await Promise.all([api.get('/wallet/'), api.get('/wallet/transactions')]);
      setWallet(w.data);
      setTxs(t.data.items);
    } catch {} finally { setRefreshing(false); }
  };
  useEffect(() => { load(); }, []);

  const buckets = wallet ? [
    { key: 'welcome', label: 'Welcome', value: wallet.welcome_credits, Icon: Gift },
    { key: 'daily', label: 'Daily', value: wallet.daily_credits, Icon: Sparkles },
    { key: 'bonus', label: 'Bonus', value: wallet.bonus_credits, Icon: Gift },
    { key: 'referral', label: 'Referral', value: wallet.referral_credits, Icon: Users },
    { key: 'purchased', label: 'Purchased', value: wallet.purchased_credits, Icon: ShoppingCart },
  ] : [];

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }}>
      <ScreenHeader title="Credit Wallet" navigation={navigation} />
      <ScrollView refreshControl={<RefreshControl refreshing={refreshing} onRefresh={load} tintColor={colors.primary} />}
        contentContainerStyle={{ padding: spacing.md, gap: spacing.md }}>
        <Card>
          <Text style={{ color: colors.textDim, fontSize: fontSize.xs, textTransform: 'uppercase', letterSpacing: 1.2 }}>Total balance</Text>
          <Text style={{ color: colors.text, fontSize: 44, fontWeight: '600', marginTop: 4, letterSpacing: -1.5 }}>
            {wallet ? Math.floor(wallet.total).toLocaleString() : '—'}
          </Text>
          <Text style={{ color: colors.textMuted, fontSize: fontSize.sm, marginTop: 4 }}>credits available</Text>
          <Button title="Recharge wallet →" style={{ marginTop: spacing.lg }} onPress={() => navigation.navigate('Billing')} />
        </Card>

        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm }}>
          {buckets.map(({ key, label, value, Icon }) => (
            <View key={key} style={{ flexBasis: '48%', flexGrow: 1, borderWidth: 1, borderColor: colors.border, borderRadius: radii.lg, backgroundColor: colors.card, padding: spacing.md }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                <Icon color={colors.primary} size={14} />
                <Text style={{ color: colors.textDim, fontSize: fontSize.xs, textTransform: 'uppercase', letterSpacing: 1 }}>{label}</Text>
              </View>
              <Text style={{ color: colors.text, fontSize: fontSize.xl, fontWeight: '600', marginTop: 4 }}>{Math.floor(value).toLocaleString()}</Text>
            </View>
          ))}
        </View>

        <Card>
          <Text style={{ color: colors.text, fontSize: fontSize.lg, fontWeight: '600', marginBottom: 8 }}>Recent transactions</Text>
          {txs.length === 0 ? (
            <Text style={{ color: colors.textMuted, textAlign: 'center', paddingVertical: 20 }}>No transactions yet</Text>
          ) : txs.slice(0, 20).map((tx) => (
            <View key={tx.id} style={{ flexDirection: 'row', alignItems: 'center', paddingVertical: 8, borderBottomWidth: 1, borderColor: colors.border + '80' }}>
              <View style={{ height: 30, width: 30, borderRadius: 6, backgroundColor: tx.amount > 0 ? colors.successDim : colors.destructiveDim, alignItems: 'center', justifyContent: 'center' }}>
                {tx.amount > 0 ? <ArrowUpRight color={colors.success} size={14} /> : <TrendingDown color={colors.destructive} size={14} />}
              </View>
              <View style={{ flex: 1, marginLeft: 10 }}>
                <Text style={{ color: colors.text, fontSize: fontSize.sm }} numberOfLines={1}>{tx.description || tx.kind}</Text>
                <Text style={{ color: colors.textDim, fontSize: fontSize.xs }}>{tx.bucket}</Text>
              </View>
              <Text style={{ color: tx.amount > 0 ? colors.success : colors.destructive, fontFamily: 'Menlo', fontSize: fontSize.sm }}>
                {tx.amount > 0 ? '+' : ''}{Math.floor(tx.amount)}
              </Text>
            </View>
          ))}
        </Card>
      </ScrollView>
    </View>
  );
}
