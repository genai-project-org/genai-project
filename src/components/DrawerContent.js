// import React from 'react';
// import { View, Text, TouchableOpacity, ScrollView, Image } from 'react-native';
// import { useSafeAreaInsets } from 'react-native-safe-area-context';
// import { useDispatch, useSelector } from 'react-redux';
// import {
//   MessageSquare, BarChart3, Wallet, CreditCard, Bell, User, Settings,
//   LogOut, Sparkles, Lock, Briefcase, Rocket, FlaskConical, GraduationCap,
//   FileText, MessagesSquare, Heart, Award, MapPin, Wrench, Code2
// } from 'lucide-react-native';
// import { colors, spacing, radii, fontSize } from '../theme';
// import { logout } from '../store/slices/authSlice';

// const primary = [
//   { label: 'AI Workspace', Icon: MessageSquare, screen: 'AI Workspace' },
//   { label: 'AI Studio', Icon: Sparkles, screen: 'AI Studio' },
//   { label: 'Code Builder', Icon: Code2, screen: 'Code Builder' },
//   { label: 'Counseling', Icon: Heart, screen: 'Counseling' },
//   { label: 'Career Intelligence', Icon: Briefcase, screen: 'Career Intelligence' },
//   { label: 'Usage', Icon: BarChart3, screen: 'Usage' },
//   { label: 'Credit Wallet', Icon: Wallet, screen: 'Wallet' },
//   { label: 'Billing', Icon: CreditCard, screen: 'Billing' },
//   { label: 'Notifications', Icon: Bell, screen: 'Notifications' },
//   { label: 'Profile', Icon: User, screen: 'Profile' },
//   { label: 'Settings', Icon: Settings, screen: 'Settings' },
// ];

// const comingSoon = [
//   { label: 'Startup Intelligence', Icon: Rocket },
//   { label: 'Research Intelligence', Icon: FlaskConical },
//   { label: 'Dynamic Course Engine', Icon: GraduationCap },
//   { label: 'Resume Intelligence', Icon: FileText },
//   { label: 'Mock Interviews', Icon: MessagesSquare },
//   { label: 'Scholarships', Icon: Award },
//   { label: 'Internships', Icon: MapPin },
//   { label: 'Freelance Intelligence', Icon: Wrench },
// ];

// export default function DrawerContent({ navigation, state }) {
//   const insets = useSafeAreaInsets();
//   const dispatch = useDispatch();
//   const user = useSelector((s) => s.auth.user);
//   const wallet = useSelector((s) => s.ui.walletBalance);
//   const active = state.routeNames[state.index];

//   return (
//     <View style={{ flex: 1, backgroundColor: colors.surface, paddingTop: insets.top }}>
//       {/* Logo */}
//       <View style={{ paddingHorizontal: spacing.lg, paddingVertical: spacing.lg, borderBottomWidth: 1, borderColor: colors.border, flexDirection: 'row', alignItems: 'center', gap: 8 }}>
//         <View style={{ height: 28, width: 28, borderRadius: 6, backgroundColor: colors.primary, alignItems: 'center', justifyContent: 'center' }}>
//           <Sparkles color="#fff" size={16} />
//         </View>
//         <Text style={{ color: colors.text, fontSize: fontSize.md, fontWeight: '600' }}>
//           IEMA<Text style={{ color: colors.primary }}>.</Text>ai
//         </Text>
//       </View>

//       <ScrollView style={{ flex: 1 }} contentContainerStyle={{ padding: spacing.sm }}>
//         {primary.map(({ label, Icon, screen }) => {
//           const isActive = active === screen;
//           return (
//             <TouchableOpacity
//               key={label}
//               onPress={() => navigation.navigate(screen)}
//               style={{
//                 flexDirection: 'row', alignItems: 'center', gap: 12,
//                 paddingHorizontal: spacing.md, paddingVertical: spacing.md,
//                 borderRadius: radii.md,
//                 backgroundColor: isActive ? colors.surfaceElevated : 'transparent',
//               }}
//             >
//               <Icon color={isActive ? colors.text : colors.textMuted} size={18} strokeWidth={1.75} />
//               <Text style={{ color: isActive ? colors.text : colors.textMuted, fontSize: fontSize.md, fontWeight: isActive ? '500' : '400' }}>{label}</Text>
//             </TouchableOpacity>
//           );
//         })}
//         <Text style={{ color: colors.textDim, fontSize: fontSize.xs, textTransform: 'uppercase', letterSpacing: 1.2, marginTop: spacing.lg, paddingHorizontal: spacing.md, paddingBottom: spacing.sm }}>Coming Soon</Text>
//         {comingSoon.map(({ label, Icon }) => (
//           <View key={label} style={{ flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: spacing.md, paddingVertical: spacing.md, opacity: 0.5 }}>
//             <Icon color={colors.textDim} size={18} strokeWidth={1.5} />
//             <Text style={{ color: colors.textDim, fontSize: fontSize.md, flex: 1 }}>{label}</Text>
//             <Lock color={colors.textDim} size={12} />
//           </View>
//         ))}
//       </ScrollView>

//       {/* Footer */}
//       <View style={{ borderTopWidth: 1, borderColor: colors.border, padding: spacing.md, paddingBottom: Math.max(insets.bottom, spacing.md) }}>
//         {wallet !== null && (
//           <View style={{ backgroundColor: colors.bg, borderWidth: 1, borderColor: colors.border, borderRadius: radii.md, padding: spacing.md, marginBottom: spacing.sm }}>
//             <Text style={{ color: colors.textDim, fontSize: fontSize.xs, textTransform: 'uppercase', letterSpacing: 1 }}>Credits</Text>
//             <Text style={{ color: colors.text, fontSize: fontSize.xl, fontWeight: '600' }}>{Math.floor(wallet).toLocaleString()}</Text>
//           </View>
//         )}
//         <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10, padding: spacing.sm }}>
//           <View style={{ height: 32, width: 32, borderRadius: 16, backgroundColor: colors.primaryDim, alignItems: 'center', justifyContent: 'center' }}>
//             <Text style={{ color: colors.primary, fontWeight: '600' }}>{(user?.name || '?').charAt(0).toUpperCase()}</Text>
//           </View>
//           <View style={{ flex: 1 }}>
//             <Text style={{ color: colors.text, fontSize: fontSize.sm }} numberOfLines={1}>{user?.name}</Text>
//             <Text style={{ color: colors.textDim, fontSize: fontSize.xs }} numberOfLines={1}>{user?.email}</Text>
//           </View>
//           <TouchableOpacity onPress={() => dispatch(logout())} style={{ padding: 6 }}>
//             <LogOut color={colors.textMuted} size={16} />
//           </TouchableOpacity>
//         </View>
//       </View>
//     </View>
//   );
// }

import React, { useMemo, useState } from "react";
import { View, Text, TouchableOpacity, ScrollView, Image } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useDispatch, useSelector } from "react-redux";

import {
  MessageSquare,
  BarChart3,
  Wallet,
  CreditCard,
  Bell,
  User,
  Settings,
  LogOut,
  Sparkles,
  Lock,
  Briefcase,
  Rocket,
  FlaskConical,
  FileText,
  MessagesSquare,
  Heart,
  Code2,
  ChevronDown,
  ChevronRight,
  Plus,
  Image as ImageIcon,
  Video,
  Mail,
  GraduationCap,
} from "lucide-react-native";

import { logout } from "../store/slices/authSlice";
import { colors, spacing, radii, fontSize } from "../theme";

const SECTION_TITLE = {
  color: colors.textDim,
  fontSize: 11,
  letterSpacing: 1.3,
  textTransform: "uppercase",
  marginTop: 20,
  marginBottom: 8,
  marginHorizontal: spacing.md,
};

const comingSoon = [
  {
    label: "Startup Intelligence",
    Icon: Rocket,
  },
  {
    label: "Research Intelligence",
    Icon: FlaskConical,
  },
  {
    label: "Resume Intelligence",
    Icon: FileText,
  },
  {
    label: "Mock Interviews",
    Icon: MessagesSquare,
  },
];

export default function DrawerContent({ navigation, state }) {
  const insets = useSafeAreaInsets();

  const dispatch = useDispatch();

  const user = useSelector((s) => s.auth.user);

  const wallet = useSelector((s) => s.ui.walletBalance);

  const active = state.routeNames[state.index];

  const [builderExpanded, setBuilderExpanded] = useState(true);

  const isBuilder = active === "Code Builder";

  const MenuItem = ({
    label,
    Icon,
    screen,
    activeItem = false,
    locked = false,
    indent = false,
    onPress,
  }) => (
    <TouchableOpacity
      disabled={locked}
      onPress={onPress ? onPress : () => screen && navigation.navigate(screen)}
      style={{
        flexDirection: "row",
        alignItems: "center",
        paddingVertical: 12,
        paddingHorizontal: indent ? 44 : 16,
        marginHorizontal: 8,
        borderRadius: 12,
        backgroundColor: activeItem ? colors.surfaceElevated : "transparent",
        opacity: locked ? 0.45 : 1,
      }}
    >
      <Icon size={18} color={activeItem ? colors.primary : colors.textMuted} />

      <Text
        style={{
          flex: 1,
          marginLeft: 12,
          color: activeItem ? colors.text : colors.textMuted,
          fontSize: fontSize.md,
          fontWeight: activeItem ? "600" : "400",
        }}
      >
        {label}
      </Text>

      {locked && <Lock size={13} color={colors.textDim} />}
    </TouchableOpacity>
  );

  return (
    <View
      style={{
        flex: 1,
        backgroundColor: colors.surface,
        paddingTop: insets.top,
      }}
    >
      {/* Header */}

      <View
        style={{
          paddingHorizontal: spacing.lg,
          paddingVertical: spacing.lg,
          borderBottomWidth: 1,
          borderColor: colors.border,
        }}
      >
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            alignSelf: "flex-start",
            marginBottom: 20,
          }}
        >
          <Image
            source={require("../../assets/logo.png")}
            style={{
              width: 36,
              height: 36,
              resizeMode: "contain",
              marginRight: 10,
            }}
          />

          <Text
            style={{
              color: colors.text,
              fontSize: 24,
              fontWeight: "700",
            }}
          >
            IEMA
            <Text style={{ color: colors.primary }}>.</Text>
            ai
          </Text>
        </View>

        <TouchableOpacity
          onPress={() => navigation.navigate("AI Workspace")}
          style={{
            marginTop: 18,
            backgroundColor: colors.surfaceElevated,
            borderRadius: 14,
            paddingVertical: 13,
            alignItems: "center",
          }}
        >
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
            }}
          >
            <Plus size={18} color={colors.primary} />

            <Text
              style={{
                color: colors.text,
                fontWeight: "600",
                marginLeft: 8,
              }}
            >
              New Chat
            </Text>
          </View>
        </TouchableOpacity>
      </View>

      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerStyle={{
          paddingVertical: 12,
          paddingBottom: 30,
        }}
      >
        {/* AI */}

        <Text style={SECTION_TITLE}>AI</Text>

        <MenuItem
          label="AI Studio"
          Icon={Sparkles}
          screen="AI Studio"
          activeItem={active === "AI Studio"}
        />

        <MenuItem
          label="AI Workspace"
          Icon={MessageSquare}
          screen="AI Workspace"
          activeItem={active === "AI Workspace"}
        />

        {/* BUILD */}

        <Text style={SECTION_TITLE}>BUILD</Text>

        <TouchableOpacity
          onPress={() => setBuilderExpanded(!builderExpanded)}
          style={{
            flexDirection: "row",
            alignItems: "center",
            paddingHorizontal: 16,
            paddingVertical: 12,
            marginHorizontal: 8,
            borderRadius: 12,
            backgroundColor: isBuilder ? colors.surfaceElevated : "transparent",
          }}
        >
          <Code2
            size={18}
            color={isBuilder ? colors.primary : colors.textMuted}
          />

          <Text
            style={{
              flex: 1,
              marginLeft: 12,
              color: isBuilder ? colors.text : colors.textMuted,
              fontWeight: "600",
            }}
          >
            Code Builder
          </Text>

          {builderExpanded ? (
            <ChevronDown size={18} color={colors.textDim} />
          ) : (
            <ChevronRight size={18} color={colors.textDim} />
          )}
        </TouchableOpacity>

        {builderExpanded && (
          <>
            <MenuItem
              indent
              label="Static Builder"
              Icon={Code2}
              screen="Code Builder"
              activeItem={isBuilder}
            />

            <MenuItem indent label="Dynamic Builder" Icon={Code2} locked />
          </>
        )}

        {/* LEARN */}

        <Text style={SECTION_TITLE}>LEARN</Text>

        <MenuItem
          label="Counseling"
          Icon={Heart}
          screen="Counseling"
          activeItem={active === "Counseling"}
        />

        <MenuItem
          label="Career Intelligence"
          Icon={Briefcase}
          screen="Career Intelligence"
          activeItem={active === "Career Intelligence"}
        />

        {/* <MenuItem label="AI Tutor" Icon={GraduationCap} locked /> */}

        {/* ACCOUNT */}

        <Text style={SECTION_TITLE}>ACCOUNT</Text>

        <MenuItem
          label="Usage"
          Icon={BarChart3}
          screen="Usage"
          activeItem={active === "Usage"}
        />

        <MenuItem
          label="Credit Wallet"
          Icon={Wallet}
          screen="Wallet"
          activeItem={active === "Wallet" || active === "Credit Wallet"}
        />

        <MenuItem
          label="Billing"
          Icon={CreditCard}
          screen="Billing"
          activeItem={active === "Billing"}
        />

        <MenuItem
          label="Notifications"
          Icon={Bell}
          screen="Notifications"
          activeItem={active === "Notifications"}
        />

        <MenuItem
          label="Profile"
          Icon={User}
          screen="Profile"
          activeItem={active === "Profile"}
        />

        <MenuItem
          label="Settings"
          Icon={Settings}
          screen="Settings"
          activeItem={active === "Settings"}
        />

        {/* COMING SOON */}

        <Text style={SECTION_TITLE}>COMING SOON</Text>

        {comingSoon.map(({ label, Icon }) => (
          <MenuItem key={label} label={label} Icon={Icon} locked />
        ))}
      </ScrollView>

      {/* Footer */}

      <View
        style={{
          borderTopWidth: 1,
          borderColor: colors.border,
          padding: spacing.md,
          paddingBottom: Math.max(insets.bottom, spacing.md),
        }}
      >
        <View
          style={{
            backgroundColor: colors.surfaceElevated,
            borderRadius: radii.lg,
            padding: spacing.md,
            marginBottom: spacing.md,
          }}
        >
          <Text
            style={{
              color: colors.textDim,
              fontSize: fontSize.xs,
              textTransform: "uppercase",
              letterSpacing: 1,
            }}
          >
            Credits Remaining
          </Text>

          <Text
            style={{
              color: colors.text,
              fontSize: 24,
              fontWeight: "700",
              marginTop: 6,
            }}
          >
            {wallet != null ? Math.floor(wallet).toLocaleString() : "--"}
          </Text>
        </View>

        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
          }}
        >
          <View
            style={{
              width: 42,
              height: 42,
              borderRadius: 21,
              backgroundColor: colors.primary,
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <Text
              style={{
                color: "#fff",
                fontWeight: "700",
                fontSize: 18,
              }}
            >
              {(user?.name || "?").charAt(0).toUpperCase()}
            </Text>
          </View>

          <View
            style={{
              flex: 1,
              marginLeft: 12,
            }}
          >
            <Text
              numberOfLines={1}
              style={{
                color: colors.text,
                fontWeight: "600",
                fontSize: fontSize.md,
              }}
            >
              {user?.name || "User"}
            </Text>

            <Text
              numberOfLines={1}
              style={{
                color: colors.textDim,
                fontSize: fontSize.sm,
                marginTop: 2,
              }}
            >
              {user?.email || ""}
            </Text>
          </View>

          <TouchableOpacity
            onPress={() => dispatch(logout())}
            style={{
              padding: 10,
            }}
          >
            <LogOut color={colors.textMuted} size={18} />
          </TouchableOpacity>
        </View>
      </View>
    </View>
  );
}
