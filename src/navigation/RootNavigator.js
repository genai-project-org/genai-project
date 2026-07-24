import React from "react";
import { useSelector } from "react-redux";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import { createDrawerNavigator } from "@react-navigation/drawer";

import LoginScreen from "../screens/LoginScreen";
import RegisterScreen from "../screens/RegisterScreen";
import ForgotPasswordScreen from "../screens/ForgotPasswordScreen";
import ChatScreen from "../screens/ChatScreen";
import ConversationsScreen from "../screens/ConversationsScreen";
import WalletScreen from "../screens/WalletScreen";
import UsageScreen from "../screens/UsageScreen";
import BillingScreen from "../screens/BillingScreen";
import ProfileScreen from "../screens/ProfileScreen";
import SettingsScreen from "../screens/SettingsScreen";
import NotificationsScreen from "../screens/NotificationsScreen";
import StudioScreen from "../screens/StudioScreen";
import CareerScreen from "../screens/CareerScreen";
import BuilderScreen from "../screens/BuilderScreen";
import CounselingScreen from "../screens/CounselingScreen";
import DrawerContent from "../components/DrawerContent";

const Stack = createNativeStackNavigator();
const Drawer = createDrawerNavigator();

function AuthStack() {
  return (
    <Stack.Navigator screenOptions={{ headerShown: false }}>
      <Stack.Screen name="Login" component={LoginScreen} />
      <Stack.Screen name="Register" component={RegisterScreen} />
      <Stack.Screen name="ForgotPassword" component={ForgotPasswordScreen} />
    </Stack.Navigator>
  );
}

function ChatStack() {
  return (
    <Stack.Navigator screenOptions={{ headerShown: false }}>
      <Stack.Screen name="Conversations" component={ConversationsScreen} />
      <Stack.Screen name="Chat" component={ChatScreen} />
    </Stack.Navigator>
  );
}

function AppDrawer() {
  return (
    <Drawer.Navigator
      drawerContent={(props) => <DrawerContent {...props} />}
      screenOptions={{ headerShown: false, drawerType: "front" }}
    >
      <Drawer.Screen name="AI Workspace" component={ChatStack} />
      <Drawer.Screen name="AI Studio" component={StudioScreen} />
      <Drawer.Screen name="Code Builder" component={BuilderScreen} />
      <Drawer.Screen name="Counseling" component={CounselingScreen} />
      <Drawer.Screen name="Career Intelligence" component={CareerScreen} />
      <Drawer.Screen name="Usage" component={UsageScreen} />
      <Drawer.Screen name="Wallet" component={WalletScreen} />
      <Drawer.Screen name="Billing" component={BillingScreen} />
      <Drawer.Screen name="Notifications" component={NotificationsScreen} />
      <Drawer.Screen name="Profile" component={ProfileScreen} />
      <Drawer.Screen name="Settings" component={SettingsScreen} />
    </Drawer.Navigator>
  );
}

export default function RootNavigator() {
  const token = useSelector((s) => s.auth.access_token);
  return token ? <AppDrawer /> : <AuthStack />;
}
