import React, { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useColors } from '@/hooks/useColors';
import { useConnection } from '@/contexts/ConnectionContext';

export default function SettingsScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const { connection, setConnection } = useConnection();

  const [baseUrl, setBaseUrl] = useState(connection.baseUrl);
  const [apiKey, setApiKey] = useState(connection.apiKey);
  const [tenant, setTenant] = useState(connection.tenant);
  const [saved, setSaved] = useState(false);

  async function save() {
    await setConnection({ baseUrl: baseUrl.trim(), apiKey: apiKey.trim(), tenant: tenant.trim() || 'demo-company' });
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  const field = (label: string, value: string, onChange: (t: string) => void, hint: string, secure = false) => (
    <View style={{ gap: 6 }}>
      <Text style={[styles.label, { color: colors.foreground }]}>{label}</Text>
      <TextInput
        value={value}
        onChangeText={onChange}
        autoCapitalize="none"
        autoCorrect={false}
        secureTextEntry={secure}
        style={[styles.input, { backgroundColor: colors.card, borderColor: colors.border, color: colors.foreground }]}
      />
      <Text style={[styles.hint, { color: colors.mutedForeground }]}>{hint}</Text>
    </View>
  );

  return (
    <View style={[styles.page, { backgroundColor: colors.background, paddingTop: insets.top }]}>
      <View style={styles.header}>
        <Text style={[styles.brand, { color: colors.mutedForeground }]}>SIGNALFORGE</Text>
        <Text style={[styles.title, { color: colors.foreground }]}>Settings</Text>
      </View>

      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 100, gap: 18 }}>
        <Text style={[styles.sectionLabel, { color: colors.mutedForeground }]}>CONNECTION</Text>
        {field('Base URL', baseUrl, setBaseUrl, 'Your SignalForge API, incl. any /api proxy prefix.')}
        {field('API key', apiKey, setApiKey, 'Sent as the X-API-Key header.', true)}
        {field('Tenant', tenant, setTenant, 'Stamped on telemetry this app sends.')}

        <Pressable onPress={save} style={[styles.save, { backgroundColor: colors.primary }]}>
          <Text style={[styles.saveText, { color: colors.primaryForeground }]}>
            {saved ? 'Saved ✓' : 'Save connection'}
          </Text>
        </Pressable>

        <View style={[styles.about, { borderColor: colors.border }]}>
          <Text style={[styles.aboutTitle, { color: colors.foreground }]}>SignalForge Mobile</Text>
          <Text style={[styles.aboutBody, { color: colors.mutedForeground }]}>
            A native client for the SignalForge incident platform. View incidents, root-cause and remediation from
            any SignalForge instance, and send test telemetry from your device. Point it at your own deployment above.
          </Text>
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1 },
  header: { paddingHorizontal: 16, paddingTop: 12, paddingBottom: 4 },
  brand: { fontSize: 11, fontFamily: 'Inter_700Bold', letterSpacing: 1.5 },
  title: { fontSize: 28, fontFamily: 'Inter_700Bold', marginTop: 2 },
  sectionLabel: { fontSize: 11, fontFamily: 'Inter_700Bold', letterSpacing: 0.8 },
  label: { fontSize: 14, fontFamily: 'Inter_600SemiBold' },
  input: { borderWidth: 1, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 11, fontSize: 14, fontFamily: 'Inter_500Medium' },
  hint: { fontSize: 12, fontFamily: 'Inter_400Regular' },
  save: { paddingVertical: 13, borderRadius: 10, alignItems: 'center' },
  saveText: { fontSize: 15, fontFamily: 'Inter_600SemiBold' },
  about: { borderTopWidth: 1, paddingTop: 16, gap: 6 },
  aboutTitle: { fontSize: 15, fontFamily: 'Inter_600SemiBold' },
  aboutBody: { fontSize: 13, fontFamily: 'Inter_400Regular', lineHeight: 19 },
});
