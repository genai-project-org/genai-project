import React, { useEffect, useState } from 'react';
import { View, Text, FlatList, TouchableOpacity, RefreshControl, Alert } from 'react-native';
import { useDispatch } from 'react-redux';
import { Plus, MessageSquare, Trash2, Pin } from 'lucide-react-native';
import api from '../api';
import { colors, spacing, fontSize, radii } from '../theme';
import ScreenHeader from '../components/ScreenHeader';
import { setWalletBalance } from '../store/slices/uiSlice';

export default function ConversationsScreen({ navigation }) {
  const [items, setItems] = useState([]);
  const [refreshing, setRefreshing] = useState(false);
  const dispatch = useDispatch();

  const load = async () => {
    setRefreshing(true);
    try {
      const { data } = await api.get('/chat/conversations');
      setItems(data.items);
      const w = await api.get('/wallet/');
      dispatch(setWalletBalance(w.data.total));
    } catch {} finally { setRefreshing(false); }
  };

  useEffect(() => {
    const unsub = navigation.addListener('focus', load);
    return unsub;
  }, [navigation]);

  const del = (id) => {
    Alert.alert('Delete chat?', 'This action cannot be undone.', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Delete', style: 'destructive', onPress: async () => {
        await api.delete(`/chat/conversations/${id}`);
        load();
      }},
    ]);
  };

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }}>
      <ScreenHeader title="AI Workspace" navigation={navigation} right={
        <TouchableOpacity
          onPress={() => navigation.navigate('Chat', { conversationId: null })}
          style={{ flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: colors.primary, paddingHorizontal: 12, paddingVertical: 8, borderRadius: radii.md }}
          testID="new-chat-btn"
        >
          <Plus color="#fff" size={16} />
          <Text style={{ color: '#fff', fontSize: fontSize.sm, fontWeight: '500' }}>New</Text>
        </TouchableOpacity>
      } />
      <FlatList
        data={items}
        keyExtractor={(item) => item.id}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={load} tintColor={colors.primary} />}
        contentContainerStyle={{ padding: spacing.md, gap: 6 }}
        ListEmptyComponent={() => (
          <View style={{ alignItems: 'center', paddingTop: 80 }}>
            <MessageSquare color={colors.textDim} size={40} />
            <Text style={{ color: colors.textMuted, marginTop: 16, fontSize: fontSize.md }}>No conversations yet</Text>
            <Text style={{ color: colors.textDim, marginTop: 4, fontSize: fontSize.sm }}>Tap New to start chatting</Text>
          </View>
        )}
        renderItem={({ item }) => (
          <TouchableOpacity
            onPress={() => navigation.navigate('Chat', { conversationId: item.id, title: item.title })}
            onLongPress={() => del(item.id)}
            style={{
              padding: spacing.md, borderRadius: radii.md, borderWidth: 1, borderColor: colors.border,
              backgroundColor: colors.card, flexDirection: 'row', alignItems: 'center', gap: 12,
            }}
            testID={`conv-${item.id}`}
          >
            <MessageSquare color={colors.textMuted} size={18} />
            <View style={{ flex: 1 }}>
              <Text style={{ color: colors.text, fontSize: fontSize.md }} numberOfLines={1}>{item.title}</Text>
              <Text style={{ color: colors.textDim, fontSize: fontSize.xs }}>{item.model_used || '—'}</Text>
            </View>
            {item.pinned && <Pin color={colors.primary} size={14} />}
          </TouchableOpacity>
        )}
      />
    </View>
  );
}
