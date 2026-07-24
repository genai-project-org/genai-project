import React from 'react';
import { View, Text, TouchableOpacity } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Menu, Sparkles } from 'lucide-react-native';
import { colors, spacing, fontSize } from '../theme';

export default function ScreenHeader({ title, navigation, right }) {
  const insets = useSafeAreaInsets();
  return (
    <View style={{
      paddingTop: insets.top,
      backgroundColor: colors.bg,
      borderBottomWidth: 1,
      borderColor: colors.border,
    }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', height: 52, paddingHorizontal: spacing.md, gap: spacing.sm }}>
        <TouchableOpacity onPress={() => navigation.toggleDrawer()} style={{ padding: 6 }} testID="drawer-toggle">
          <Menu color={colors.text} size={22} />
        </TouchableOpacity>
        <View style={{ flex: 1, flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          <Sparkles color={colors.primary} size={16} />
          <Text style={{ color: colors.text, fontSize: fontSize.md, fontWeight: '600' }}>{title}</Text>
        </View>
        {right}
      </View>
    </View>
  );
}
