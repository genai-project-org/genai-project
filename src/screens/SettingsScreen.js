import React, { useEffect, useState } from 'react';
import { View, Text, ScrollView, Alert, TouchableOpacity } from 'react-native';
import { useDispatch, useSelector } from 'react-redux';
import api from '../api';
import { logout, setAuth } from '../store/slices/authSlice';
import ScreenHeader from '../components/ScreenHeader';
import { Card, Button, Input, Label } from '../components/UI';
import { colors, spacing, fontSize, radii } from '../theme';

const AI_PROVIDERS = [
  { key: 'iema', label: 'IEMA (recommended)', desc: 'Data lake first, then random Claude/OpenAI.' },
  { key: 'claude', label: 'Claude', desc: 'Anthropic Claude Haiku 4.5.' },
  { key: 'openai', label: 'OpenAI', desc: 'OpenAI GPT-4o mini.' },
];

export default function SettingsScreen({ navigation }) {
  const dispatch = useDispatch();
  const user = useSelector(s => s.auth.user);
  const [confirmText, setConfirmText] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [provider, setProvider] = useState(user?.ai_provider || 'iema');

  useEffect(() => { setProvider(user?.ai_provider || 'iema'); }, [user]);

  const saveProvider = async (p) => {
    if (p === provider) return;
    setProvider(p);
    try {
      const { data } = await api.patch('/auth/me', { ai_provider: p });
      dispatch(setAuth({ user: data }));
    } catch {}
  };

  const doDelete = () => {
    if (confirmText !== 'DELETE') { Alert.alert('Type DELETE', 'Please type DELETE to confirm'); return; }
    Alert.alert('Confirm account deletion', 'This action cannot be undone. All your data will be permanently removed.', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Delete permanently', style: 'destructive', onPress: async () => {
        setDeleting(true);
        try {
          await api.delete('/auth/me');
          dispatch(logout());
        } catch { Alert.alert('Error', 'Failed to delete account'); } finally { setDeleting(false); }
      }},
    ]);
  };

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }}>
      <ScreenHeader title="Settings" navigation={navigation} />
      <ScrollView contentContainerStyle={{ padding: spacing.md, gap: spacing.md }}>
        <Card>
          <Text style={{ color: colors.text, fontSize: fontSize.lg, fontWeight: '600' }}>AI Provider</Text>
          <Text style={{ color: colors.textMuted, fontSize: fontSize.sm, marginTop: 4, marginBottom: spacing.md }}>
            Choose which model powers your AI experiences.
          </Text>
          {AI_PROVIDERS.map(p => (
            <TouchableOpacity key={p.key} onPress={() => saveProvider(p.key)}
              testID={`provider-${p.key}`}
              style={{ padding: 10, marginBottom: 6, borderRadius: radii.md, borderWidth: 1,
                borderColor: provider === p.key ? colors.primary : colors.border,
                backgroundColor: provider === p.key ? colors.primaryDim : 'transparent' }}>
              <Text style={{ color: provider === p.key ? colors.primary : colors.text, fontSize: fontSize.sm, fontWeight: '500' }}>{p.label}</Text>
              <Text style={{ color: colors.textDim, fontSize: fontSize.xs, marginTop: 2 }}>{p.desc}</Text>
            </TouchableOpacity>
          ))}
        </Card>

        <Card>
          <Text style={{ color: colors.text, fontSize: fontSize.lg, fontWeight: '600' }}>Appearance</Text>
          <Text style={{ color: colors.textMuted, fontSize: fontSize.sm, marginTop: 4 }}>
            IEMA.ai mobile uses your device's system theme (dark by default). You can change this in your device settings.
          </Text>
        </Card>

        <Card style={{ borderColor: colors.destructive + '80', backgroundColor: colors.destructiveDim }}>
          <Text style={{ color: colors.destructive, fontSize: fontSize.lg, fontWeight: '600' }}>Danger zone</Text>
          <Text style={{ color: colors.textMuted, fontSize: fontSize.sm, marginTop: 4 }}>
            Deleting your account is permanent. Your conversations, credits and payment history will be erased.
          </Text>
          <View style={{ marginTop: spacing.md, gap: 8 }}>
            <Label>Type DELETE to confirm</Label>
            <Input value={confirmText} onChangeText={setConfirmText} placeholder="DELETE" autoCapitalize="characters" testID="delete-confirm" />
            <Button title="Permanently delete account" variant="outline" onPress={doDelete} loading={deleting} testID="delete-account" />
          </View>
        </Card>

        <Button title="Sign out" variant="outline" onPress={() => dispatch(logout())} testID="sign-out" />

        <Text style={{ color: colors.textDim, fontSize: 11, textAlign: 'center', marginTop: 20 }}>IEMA.ai v2.0 · Build 1</Text>
      </ScrollView>
    </View>
  );
}
