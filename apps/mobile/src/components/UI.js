import React from 'react';
import { View, Text, TouchableOpacity, ActivityIndicator, TextInput } from 'react-native';
import { colors, spacing, radii, fontSize } from '../theme';

export function Button({ title, onPress, variant = 'primary', loading, disabled, style, testID }) {
  const isPrimary = variant === 'primary';
  const isOutline = variant === 'outline';
  const bg = disabled ? colors.borderStrong : isPrimary ? colors.primary : isOutline ? 'transparent' : colors.surfaceElevated;
  const borderColor = isOutline ? colors.border : bg;
  const textColor = disabled ? colors.textMuted : isPrimary ? '#fff' : colors.text;
  return (
    <TouchableOpacity
      testID={testID}
      onPress={onPress}
      disabled={disabled || loading}
      activeOpacity={0.85}
      style={[{
        height: 46, borderRadius: radii.md, backgroundColor: bg, borderWidth: 1, borderColor,
        alignItems: 'center', justifyContent: 'center', flexDirection: 'row', gap: 8,
      }, style]}
    >
      {loading ? <ActivityIndicator color={textColor} size="small" /> : (
        <Text style={{ color: textColor, fontSize: fontSize.md, fontWeight: '500' }}>{title}</Text>
      )}
    </TouchableOpacity>
  );
}

export function Input({ value, onChangeText, placeholder, secureTextEntry, keyboardType, autoCapitalize = 'none', testID, style, multiline, ...rest }) {
  return (
    <TextInput
      testID={testID}
      value={value}
      onChangeText={onChangeText}
      placeholder={placeholder}
      placeholderTextColor={colors.textDim}
      secureTextEntry={secureTextEntry}
      keyboardType={keyboardType}
      autoCapitalize={autoCapitalize}
      autoCorrect={false}
      multiline={multiline}
      style={[{
        borderWidth: 1, borderColor: colors.border, borderRadius: radii.md,
        backgroundColor: colors.surface, color: colors.text, fontSize: fontSize.md,
        paddingHorizontal: spacing.md, paddingVertical: 12, minHeight: 46,
      }, style]}
      {...rest}
    />
  );
}

export function Card({ children, style }) {
  return (
    <View style={[{
      borderWidth: 1, borderColor: colors.border, borderRadius: radii.lg,
      backgroundColor: colors.card, padding: spacing.lg,
    }, style]}>
      {children}
    </View>
  );
}

export function Label({ children }) {
  return <Text style={{ color: colors.textMuted, fontSize: fontSize.sm, marginBottom: 6 }}>{children}</Text>;
}

export function Divider() {
  return <View style={{ height: 1, backgroundColor: colors.border, marginVertical: spacing.md }} />;
}

export function StatCard({ label, value, sub }) {
  return (
    <Card style={{ flex: 1 }}>
      <Text style={{ color: colors.textDim, fontSize: fontSize.xs, textTransform: 'uppercase', letterSpacing: 1.2 }}>{label}</Text>
      <Text style={{ color: colors.text, fontSize: fontSize.xxl, fontWeight: '600', marginTop: 4 }}>{value}</Text>
      {sub && <Text style={{ color: colors.textDim, fontSize: fontSize.xs, marginTop: 2 }}>{sub}</Text>}
    </Card>
  );
}
