import { polyfillGlobal } from "react-native/Libraries/Utilities/PolyfillFunctions";
import { fetch } from "react-native-fetch-api";

polyfillGlobal("fetch", () => fetch);
import React, { useEffect } from 'react';
import { Provider, useDispatch, useSelector } from 'react-redux';
import { StatusBar } from 'expo-status-bar';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { NavigationContainer } from '@react-navigation/native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { View, ActivityIndicator, Text } from 'react-native';

import { store } from './src/store/store';
import { hydrate } from './src/store/slices/authSlice';
import { loadAuth } from './src/authStorage';
import { colors } from './src/theme';
import RootNavigator from './src/navigation/RootNavigator';

const navTheme = {
  dark: true,
  colors: {
    primary: colors.primary,
    background: colors.bg,
    card: colors.surface,
    text: colors.text,
    border: colors.border,
    notification: colors.primary,
  },
  fonts: {
    regular: { fontFamily: 'System', fontWeight: '400' },
    medium: { fontFamily: 'System', fontWeight: '500' },
    bold: { fontFamily: 'System', fontWeight: '600' },
    heavy: { fontFamily: 'System', fontWeight: '700' },
  },
};

function Root() {
  const dispatch = useDispatch();
  const hydrated = useSelector((s) => s.auth.hydrated);

  useEffect(() => {
    (async () => {
      const persisted = await loadAuth();
      dispatch(hydrate(persisted));
    })();
  }, [dispatch]);

  if (!hydrated) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.bg, alignItems: 'center', justifyContent: 'center' }}>
        <ActivityIndicator color={colors.primary} size="large" />
        <Text style={{ color: colors.textMuted, marginTop: 12 }}>IEMA.ai</Text>
      </View>
    );
  }

  return (
    <NavigationContainer theme={navTheme}>
      <RootNavigator />
    </NavigationContainer>
  );
}

export default function App() {
  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <Provider store={store}>
          <StatusBar style="light" />
          <Root />
        </Provider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
