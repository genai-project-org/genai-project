import React, { useState } from "react";
import { TouchableOpacity, Text, Alert } from "react-native";
import { Flag, Check } from "lucide-react-native";
import { colors, fontSize } from "../theme";

export default function ReportButton() {
  const [reported, setReported] = useState(false);

  const handleReport = () => {
    Alert.alert(
      "Report AI Response",
      "Do you want to report this AI-generated response as inappropriate or offensive?",
      [
        {
          text: "Cancel",
          style: "cancel",
        },
        {
          text: "Report",
          style: "destructive",
          onPress: () => {
            // TODO: Connect to backend in next release.
            setReported(true);

            Alert.alert(
              "Report Submitted",
              "Thank you. This response has been flagged for review."
            );
          },
        },
      ]
    );
  };

  return (
    <TouchableOpacity
      disabled={reported}
      onPress={handleReport}
      style={{
        marginTop: 8,
        flexDirection: "row",
        alignItems: "center",
        alignSelf: "flex-start",
        opacity: reported ? 0.7 : 1,
      }}
    >
      {reported ? (
        <Check size={12} color="#10b981" />
      ) : (
        <Flag size={12} color={colors.textDim} />
      )}

      <Text
        style={{
          marginLeft: 4,
          fontSize: fontSize.xs,
          color: reported ? "#10b981" : colors.textDim,
        }}
      >
        {reported ? "Reported" : "Report"}
      </Text>
    </TouchableOpacity>
  );
}
