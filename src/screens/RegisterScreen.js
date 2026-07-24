import React, { useState } from 'react';
import { View, Text, ScrollView, KeyboardAvoidingView, Platform, Alert } from 'react-native';
import { useDispatch } from 'react-redux';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Sparkles } from 'lucide-react-native';
import api from '../api';
import { setAuth } from '../store/slices/authSlice';
import { colors, spacing, fontSize } from '../theme';
import { Button, Input, Label } from '../components/UI';
import SocialAuthButtons from '../components/SocialAuthButtons';

export default function RegisterScreen({ navigation }) {
  const insets = useSafeAreaInsets();
  const dispatch = useDispatch();
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);

  const submit = async () => {
    if (!name || !email || password.length < 6) {
      Alert.alert('Missing info', 'Fill all fields, password must be 6+ chars');
      return;
    }
    setLoading(true);
    try {
      const { data } = await api.post('/auth/register', { name, email, password });
      dispatch(setAuth(data));
    } catch (err) {
      Alert.alert('Registration failed', err.response?.data?.detail || 'Please try again');
    } finally { setLoading(false); }
  };

  return (
    <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1, backgroundColor: colors.bg }}>
      <ScrollView contentContainerStyle={{ paddingTop: insets.top + 40, paddingHorizontal: spacing.xl, paddingBottom: spacing.xl }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 40 }}>
          <View style={{ height: 28, width: 28, borderRadius: 6, backgroundColor: colors.primary, alignItems: 'center', justifyContent: 'center' }}>
            <Sparkles color="#fff" size={16} />
          </View>
          <Text style={{ color: colors.text, fontSize: fontSize.md, fontWeight: '600' }}>IEMA<Text style={{ color: colors.primary }}>.</Text>ai</Text>
        </View>
        <Text style={{ color: colors.text, fontSize: fontSize.hero, fontWeight: '600', letterSpacing: -1 }}>Create account</Text>
        <Text style={{ color: colors.textMuted, fontSize: fontSize.md, marginTop: 8 }}>Start with 100 free credits. No card required.</Text>

        <View style={{ marginTop: 32 }}>
          <SocialAuthButtons />
        </View>

        <View style={{ gap: 12 }}>
          <View>
            <Label>Full name</Label>
            <Input value={name} onChangeText={setName} placeholder="Jane Doe" autoCapitalize="words" testID="register-name" />
          </View>
          <View>
            <Label>Email</Label>
            <Input value={email} onChangeText={setEmail} placeholder="you@company.com" keyboardType="email-address" testID="register-email" />
          </View>
          <View>
            <Label>Password</Label>
            <Input value={password} onChangeText={setPassword} placeholder="••••••••" secureTextEntry testID="register-password" />
          </View>
          <Button title="Create account" onPress={submit} loading={loading} testID="register-submit" />
        </View>

        <View style={{ marginTop: 24, alignItems: 'center' }}>
          <Text style={{ color: colors.textMuted, fontSize: fontSize.sm }}>
            Already have an account?{' '}
            <Text style={{ color: colors.primary, fontWeight: '500' }} onPress={() => navigation.navigate('Login')}>Sign in</Text>
          </Text>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}
