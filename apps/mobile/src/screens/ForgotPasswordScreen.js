import React, { useState } from 'react';
import { View, Text, ScrollView, Alert } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { ShieldCheck, MailCheck } from 'lucide-react-native';
import api from '../api';
import { colors, spacing, fontSize } from '../theme';
import { Button, Input, Label } from '../components/UI';

/**
 * Two-step OTP-based recovery on mobile — mirrors the web flow.
 *   request → verify → reset → done
 * The OTP has to be re-entered on the same device that initiated the flow,
 * so an attacker who owns only the email inbox cannot use it.
 */
export default function ForgotPasswordScreen({ navigation }) {
  const insets = useSafeAreaInsets();
  const [step, setStep] = useState('request');
  const [email, setEmail] = useState('');
  const [otp, setOtp] = useState('');
  const [resetToken, setResetToken] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [loading, setLoading] = useState(false);

  const sendCode = async () => {
    if (!email) return;
    setLoading(true);
    try {
      await api.post('/auth/forgot-password', { email });
      setStep('verify');
    } catch {
      Alert.alert('Error', 'Could not send code. Try again.');
    } finally { setLoading(false); }
  };

  const verifyCode = async () => {
    setLoading(true);
    try {
      const { data } = await api.post('/auth/verify-reset-otp', { email, otp });
      setResetToken(data.reset_token);
      setStep('reset');
    } catch (err) {
      Alert.alert('Invalid code', err.response?.data?.detail || 'The code you entered is invalid or expired.');
    } finally { setLoading(false); }
  };

  const resetPassword = async () => {
    setLoading(true);
    try {
      await api.post('/auth/reset-password', { token: resetToken, new_password: newPassword });
      setStep('done');
      setTimeout(() => navigation.navigate('Login'), 1200);
    } catch (err) {
      Alert.alert('Reset failed', err.response?.data?.detail || 'Could not update password.');
    } finally { setLoading(false); }
  };

  return (
    <ScrollView
      contentContainerStyle={{
        flexGrow: 1,
        paddingTop: insets.top + 40,
        paddingHorizontal: spacing.xl,
        backgroundColor: colors.bg,
      }}
    >
      {step === 'request' && (
        <>
          <Text style={{ color: colors.text, fontSize: fontSize.hero, fontWeight: '600', letterSpacing: -1 }}>Forgot password?</Text>
          <Text style={{ color: colors.textMuted, fontSize: fontSize.md, marginTop: 8 }}>
            Enter your email — we'll send you a 6-digit code.
          </Text>
          <View style={{ marginTop: 32, gap: 12 }}>
            <View>
              <Label>Email</Label>
              <Input value={email} onChangeText={setEmail} placeholder="you@company.com"
                     keyboardType="email-address" autoCapitalize="none" testID="forgot-email" />
            </View>
            <Button title="Send reset code" onPress={sendCode} loading={loading} testID="forgot-submit" />
            <Button title="Back to sign in" variant="outline" onPress={() => navigation.navigate('Login')} />
          </View>
        </>
      )}

      {step === 'verify' && (
        <>
          <View style={{ height: 56, width: 56, borderRadius: 14, backgroundColor: colors.primaryDim, borderWidth: 1, borderColor: colors.primary, alignItems: 'center', justifyContent: 'center' }}>
            <ShieldCheck color={colors.primary} size={26} />
          </View>
          <Text style={{ color: colors.text, fontSize: fontSize.xxl, fontWeight: '600', marginTop: 20 }}>Enter your code</Text>
          <Text style={{ color: colors.textMuted, marginTop: 8 }}>
            We sent a 6-digit code to <Text style={{ color: colors.text }}>{email}</Text>. It expires in 10 minutes.
          </Text>
          <View style={{ marginTop: 24, gap: 12 }}>
            <View>
              <Label>Verification code</Label>
              <Input
                value={otp}
                onChangeText={(t) => setOtp(t.replace(/[^0-9]/g, '').slice(0, 6))}
                placeholder="123456"
                keyboardType="number-pad"
                testID="forgot-otp"
                style={{
                  fontSize: 22,
                  letterSpacing: 8,
                  textAlign: 'center',
                  fontFamily: 'monospace',
                }}
              />
            </View>
            <Button title="Verify code" onPress={verifyCode} loading={loading}
                    disabled={otp.length !== 6} testID="forgot-verify" />
            <Button title="Use a different email" variant="outline" onPress={() => setStep('request')} />
          </View>
        </>
      )}

      {step === 'reset' && (
        <>
          <Text style={{ color: colors.text, fontSize: fontSize.xxl, fontWeight: '600' }}>Choose a new password</Text>
          <Text style={{ color: colors.textMuted, marginTop: 8 }}>
            All other signed-in sessions will be signed out.
          </Text>
          <View style={{ marginTop: 24, gap: 12 }}>
            <View>
              <Label>New password</Label>
              <Input value={newPassword} onChangeText={setNewPassword}
                     placeholder="Minimum 8 characters" secureTextEntry testID="forgot-new-password" />
            </View>
            <Button title="Save new password" onPress={resetPassword} loading={loading}
                    disabled={newPassword.length < 8} testID="forgot-save" />
          </View>
        </>
      )}

      {step === 'done' && (
        <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center' }}>
          <View style={{ height: 56, width: 56, borderRadius: 14, backgroundColor: colors.primaryDim, borderWidth: 1, borderColor: colors.primary, alignItems: 'center', justifyContent: 'center' }}>
            <MailCheck color={colors.primary} size={26} />
          </View>
          <Text style={{ color: colors.text, fontSize: fontSize.xxl, fontWeight: '600', marginTop: 20 }}>Password updated</Text>
          <Text style={{ color: colors.textMuted, textAlign: 'center', marginTop: 8 }}>Redirecting you to sign in…</Text>
        </View>
      )}
    </ScrollView>
  );
}
