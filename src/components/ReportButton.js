import React, { useState } from "react";
import { TouchableOpacity, Text, Alert } from "react-native";
import { Flag, Check } from "lucide-react-native";
import { colors, fontSize } from "../theme";
import api from "../api";

/**
 * Lets a user flag AI-generated content as offensive without leaving the
 * app (Google Play "AI-Generated Content" policy requirement). Submits to
 * `POST /reports/` so flags feed moderation instead of only toasting locally.
 *
 * @param {string} contentType - e.g. "studio_image", "studio_video", "chat"
 * @param {string} [contentRef] - url or id of the flagged content
 * @param {string} [contentPreview] - short prompt/text for moderator context
 */
export default function ReportButton({ contentType = "ai_response", contentRef, contentPreview }) {
  const [reported, setReported] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const submitReport = async () => {
    setSubmitting(true);
    try {
      await api.post("/reports/", {
        content_type: contentType,
        content_ref: contentRef,
        content_preview: contentPreview ? String(contentPreview).slice(0, 500) : undefined,
      });
      setReported(true);
      Alert.alert(
        "Report Submitted",
        "Thank you. This content has been flagged for review."
      );
    } catch (e) {
      Alert.alert(
        "Report Failed",
        "We couldn't submit your report right now. Please try again."
      );
    } finally {
      setSubmitting(false);
    }
  };

  const handleReport = () => {
    Alert.alert(
      "Report AI Content",
      "Do you want to report this AI-generated content as inappropriate or offensive?",
      [
        {
          text: "Cancel",
          style: "cancel",
        },
        {
          text: "Report",
          style: "destructive",
          onPress: submitReport,
        },
      ]
    );
  };

  return (
    <TouchableOpacity
      disabled={reported || submitting}
      onPress={handleReport}
      style={{
        marginTop: 8,
        flexDirection: "row",
        alignItems: "center",
        alignSelf: "flex-start",
        opacity: reported ? 0.7 : submitting ? 0.5 : 1,
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
        {reported ? "Reported" : submitting ? "Reporting…" : "Report"}
      </Text>
    </TouchableOpacity>
  );
}
