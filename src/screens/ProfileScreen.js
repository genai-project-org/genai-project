import React, { useEffect, useState } from 'react';
import { View, Text, ScrollView, Alert } from 'react-native';
import { useSelector, useDispatch } from 'react-redux';
import { MailCheck, ShieldCheck } from 'lucide-react-native';
import api from '../api';
import { setUser } from '../store/slices/authSlice';
import ScreenHeader from '../components/ScreenHeader';
import { Card, Button, Input, Label } from '../components/UI';
import { colors, spacing, fontSize, radii } from '../theme';

export default function ProfileScreen({ navigation }) {
  const user = useSelector((s) => s.auth.user);
  const dispatch = useDispatch();
  const [name, setName] = useState(user?.name || '');
  const [saving, setSaving] = useState(false);
  const [sendingCode, setSendingCode] = useState(false);
  const [code, setCode] = useState('');
  const [showVerify, setShowVerify] = useState(false);
  const [verifying, setVerifying] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      const { data } = await api.patch('/auth/me', { name });
      dispatch(setUser(data));
      Alert.alert('Saved', 'Profile updated');
    } catch { Alert.alert('Error', 'Failed to update'); } finally { setSaving(false); }
  };

  const sendCode = async () => {
    setSendingCode(true);
    try {
      await api.post('/auth/send-verify-email');
      Alert.alert('Code sent', `A 6-digit code was sent to ${user.email}`);
      setShowVerify(true);
    } catch { Alert.alert('Error', 'Failed to send code'); } finally { setSendingCode(false); }
  };

  const verify = async () => {
    setVerifying(true);
    try {
      await api.post('/auth/verify-email', { code });
      const { data } = await api.get('/auth/me');
      dispatch(setUser(data));
      setShowVerify(false);
      setCode('');
      Alert.alert('Email verified!', 'Your account is now verified.');
    } catch (e) {
      Alert.alert('Invalid code', e.response?.data?.detail || 'Try again');
    } finally { setVerifying(false); }
  };

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }}>
      <ScreenHeader title="Profile" navigation={navigation} />
      <ScrollView contentContainerStyle={{ padding: spacing.md, gap: spacing.md }}>
        {!user?.email_verified && (
          <Card style={{ borderColor: colors.primary + '80', backgroundColor: colors.primaryDim }}>
            <Text style={{ color: colors.text, fontSize: fontSize.md, fontWeight: '500' }}>Verify your email</Text>
            <Text style={{ color: colors.textMuted, fontSize: fontSize.sm, marginTop: 4 }}>We'll send a 6-digit code to {user?.email}</Text>
            <Button title={showVerify ? 'Resend code' : 'Send code'} onPress={sendCode} loading={sendingCode} style={{ marginTop: spacing.md, alignSelf: 'flex-start', paddingHorizontal: 24 }} testID="verify-send" />
            {showVerify && (
              <View style={{ marginTop: spacing.md, gap: 8 }}>
                <Input value={code} onChangeText={(v) => setCode(v.replace(/\D/g, '').slice(0, 6))} placeholder="000000" keyboardType="number-pad" style={{ textAlign: 'center', fontSize: 24, letterSpacing: 8, fontFamily: 'Menlo' }} testID="verify-code" />
                <Button title="Verify" onPress={verify} loading={verifying} disabled={code.length !== 6} testID="verify-submit" />
              </View>
            )}
          </Card>
        )}

        <Card>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12, marginBottom: 16 }}>
            <View style={{ height: 56, width: 56, borderRadius: 28, backgroundColor: colors.primaryDim, alignItems: 'center', justifyContent: 'center' }}>
              <Text style={{ color: colors.primary, fontSize: 24, fontWeight: '600' }}>{(user?.name || '?').charAt(0).toUpperCase()}</Text>
            </View>
            <View style={{ flex: 1 }}>
              <Text style={{ color: colors.text, fontSize: fontSize.lg, fontWeight: '600' }}>{user?.name}</Text>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
                <Text style={{ color: colors.textMuted, fontSize: fontSize.sm }}>{user?.email}</Text>
                {user?.email_verified && <MailCheck color={colors.success} size={12} />}
              </View>
            </View>
          </View>
          <View style={{ gap: 12 }}>
            <View>
              <Label>Full name</Label>
              <Input value={name} onChangeText={setName} autoCapitalize="words" />
            </View>
            <Button title="Save changes" onPress={save} loading={saving} />
          </View>
        </Card>

        <Card>
          <Text style={{ color: colors.text, fontSize: fontSize.lg, fontWeight: '600', marginBottom: 8 }}>Connected accounts</Text>
          {[
            { p: 'Google', connected: user?.provider === 'google' },
            { p: 'Microsoft', connected: user?.provider === 'microsoft' },
            { p: 'Apple', connected: false },
          ].map(({ p, connected }) => (
            <View key={p} style={{ flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 10, borderBottomWidth: 1, borderColor: colors.border + '80' }}>
              <Text style={{ color: colors.text, fontSize: fontSize.sm }}>{p}</Text>
              <View style={{ paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999, borderWidth: 1, borderColor: connected ? colors.success : colors.border }}>
                <Text style={{ color: connected ? colors.success : colors.textDim, fontSize: 11 }}>{connected ? 'Connected' : 'Not connected'}</Text>
              </View>
            </View>
          ))}
        </Card>
      </ScrollView>
    </View>
  );
}
