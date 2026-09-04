import React, { useEffect, useState } from 'react';
import { View, Text, FlatList, RefreshControl, TouchableOpacity } from 'react-native';
import { Bell, Trash2, CheckCheck } from 'lucide-react-native';
import api from '../api';
import ScreenHeader from '../components/ScreenHeader';
import { Card } from '../components/UI';
import { colors, spacing, fontSize, radii } from '../theme';

export default function NotificationsScreen({ navigation }) {
  const [items, setItems] = useState([]);
  const [refreshing, setRefreshing] = useState(false);

  const load = async () => {
    setRefreshing(true);
    try {
      const { data } = await api.get('/notifications/');
      setItems(data.items);
    } catch {} finally { setRefreshing(false); }
  };
  useEffect(() => { load(); }, []);

  const markAll = async () => { await api.post('/notifications/mark-all-read'); load(); };
  const del = async (id) => { await api.delete(`/notifications/${id}`); load(); };
  const markRead = async (id) => { await api.post(`/notifications/${id}/read`); load(); };

  const anyUnread = items.some(n => !n.read);

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }}>
      <ScreenHeader title="Notifications" navigation={navigation} right={
        anyUnread ? (
          <TouchableOpacity onPress={markAll} style={{ flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 10, paddingVertical: 6 }}>
            <CheckCheck color={colors.primary} size={14} />
            <Text style={{ color: colors.primary, fontSize: fontSize.xs }}>Mark all</Text>
          </TouchableOpacity>
        ) : null
      } />
      <FlatList
        data={items}
        keyExtractor={(item) => item.id}
        contentContainerStyle={{ padding: spacing.md, gap: 8 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={load} tintColor={colors.primary} />}
        ListEmptyComponent={() => (
          <View style={{ alignItems: 'center', paddingTop: 80 }}>
            <Bell color={colors.textDim} size={40} />
            <Text style={{ color: colors.textMuted, marginTop: 16 }}>No notifications yet</Text>
          </View>
        )}
        renderItem={({ item }) => (
          <TouchableOpacity
            onPress={() => !item.read && markRead(item.id)}
            style={{
              padding: spacing.md,
              borderWidth: 1, borderRadius: radii.lg,
              borderColor: item.read ? colors.border : colors.primary + '80',
              backgroundColor: item.read ? colors.card : colors.primaryDim,
              flexDirection: 'row', alignItems: 'flex-start', gap: 10,
            }}
          >
            <View style={{ height: 8, width: 8, borderRadius: 4, marginTop: 6, backgroundColor: item.read ? colors.textDim : colors.primary }} />
            <View style={{ flex: 1 }}>
              <Text style={{ color: colors.text, fontSize: fontSize.md, fontWeight: '500' }}>{item.title}</Text>
              {item.body ? <Text style={{ color: colors.textMuted, fontSize: fontSize.sm, marginTop: 2 }}>{item.body}</Text> : null}
            </View>
            <TouchableOpacity onPress={() => del(item.id)} style={{ padding: 4 }}>
              <Trash2 color={colors.textMuted} size={14} />
            </TouchableOpacity>
          </TouchableOpacity>
        )}
      />
    </View>
  );
}
