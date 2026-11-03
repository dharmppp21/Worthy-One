import React, { useState } from 'react';
import {
  ActivityIndicator,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useQuery } from '@tanstack/react-query';
import * as Haptics from 'expo-haptics';
import { useColors } from '@/hooks/useColors';
import { useConnection } from '@/contexts/ConnectionContext';
import { getHealth, otlpEndpoint, sendTestTraffic, SignalForgeError } from '@/lib/signalforge';

export default function ConnectScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const { connection } = useConnection();
  const [service, setService] = useState('mobile-demo');
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  const healthQ = useQuery({
    queryKey: ['health', connection.baseUrl, connection.apiKey],
    queryFn: () => getHealth(connection),
    refetchInterval: 20000,
  });

  const connected = healthQ.data?.status === 'ok';
  const otlp = otlpEndpoint(connection);
  const snippet =
    `OTEL_EXPORTER_OTLP_ENDPOINT=${connection.baseUrl}\n` +
    `OTEL_EXPORTER_OTLP_HEADERS=x-api-key=${connection.apiKey}\n` +
    `OTEL_SERVICE_NAME=your-service`;

  async function sendTraffic(failing: boolean) {
    setSending(true);
    setResult(null);
    if (Platform.OS !== 'web') Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    try {
      await sendTestTraffic(connection, service.trim() || 'mobile-demo', { count: 25, failing });
      setResult(
        failing
          ? `Sent 25 failing requests as "${service.trim() || 'mobile-demo'}". Open the Incidents tab in a few seconds.`
          : `Sent 25 healthy requests as "${service.trim() || 'mobile-demo'}".`,
      );
    } catch (e) {
      setResult(e instanceof SignalForgeError ? e.message : 'Failed to send telemetry.');
    } finally {
      setSending(false);
    }
  }

  return (
    <View style={[styles.page, { backgroundColor: colors.background, paddingTop: insets.top }]}>
      <View style={styles.header}>
        <Text style={[styles.brand, { color: colors.mutedForeground }]}>SIGNALFORGE</Text>
        <Text style={[styles.title, { color: colors.foreground }]}>Connect</Text>
      </View>

      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 100, gap: 16 }}>
        {/* Status */}
        <View style={[styles.card, { backgroundColor: colors.card, borderColor: colors.border }]}>
          <View style={styles.statusRow}>
            <View
              style={[
                styles.statusDot,
                { backgroundColor: healthQ.isLoading ? colors.warning : connected ? colors.success : colors.destructive },
              ]}
            />
            <Text style={[styles.statusText, { color: colors.foreground }]}>
              {healthQ.isLoading ? 'Checking…' : connected ? 'Connected' : 'Unreachable'}
            </Text>
          </View>
          <Text style={[styles.mono, { color: colors.mutedForeground }]} selectable>
            {connection.baseUrl}
          </Text>
        </View>

        {/* Connect another system */}
        <View style={{ gap: 8 }}>
          <Text style={[styles.sectionLabel, { color: colors.mutedForeground }]}>CONNECT A SYSTEM</Text>
          <Text style={[styles.help, { color: colors.mutedForeground }]}>
            Point any OpenTelemetry-instrumented service at SignalForge with these three env vars:
          </Text>
          <View style={[styles.card, { backgroundColor: colors.card, borderColor: colors.border }]}>
            <Text style={[styles.mono, { color: colors.foreground }]} selectable>
              {snippet}
            </Text>
          </View>
          <Text style={[styles.help, { color: colors.mutedForeground }]}>Or POST OTLP traces directly to:</Text>
          <View style={[styles.card, { backgroundColor: colors.card, borderColor: colors.border }]}>
            <Text style={[styles.mono, { color: colors.foreground }]} selectable>
              {otlp}
            </Text>
          </View>
        </View>

        {/* Send test telemetry from this device */}
        <View style={{ gap: 8 }}>
          <Text style={[styles.sectionLabel, { color: colors.mutedForeground }]}>SEND TEST TELEMETRY</Text>
          <Text style={[styles.help, { color: colors.mutedForeground }]}>
            This device posts request metrics to SignalForge — a quick way to prove the pipeline from your phone.
          </Text>
          <TextInput
            value={service}
            onChangeText={setService}
            placeholder="service name"
            placeholderTextColor={colors.mutedForeground}
            autoCapitalize="none"
            style={[styles.input, { backgroundColor: colors.card, borderColor: colors.border, color: colors.foreground }]}
          />
          <View style={styles.actions}>
            <Pressable
              disabled={sending}
              onPress={() => sendTraffic(true)}
              style={[styles.btn, { backgroundColor: colors.destructive }, sending && { opacity: 0.5 }]}
            >
              <Text style={[styles.btnText, { color: '#fff' }]}>
                {sending ? 'Sending…' : 'Send failing traffic → incident'}
              </Text>
            </Pressable>
            <Pressable
              disabled={sending}
              onPress={() => sendTraffic(false)}
              style={[styles.btn, styles.btnGhost, { borderColor: colors.border }, sending && { opacity: 0.5 }]}
            >
              <Text style={[styles.btnText, { color: colors.foreground }]}>Healthy</Text>
            </Pressable>
          </View>
          {result && <Text style={[styles.result, { color: colors.foreground }]}>{result}</Text>}
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
  card: { borderWidth: 1, borderRadius: 12, padding: 14, gap: 8 },
  statusRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  statusDot: { width: 10, height: 10, borderRadius: 5 },
  statusText: { fontSize: 15, fontFamily: 'Inter_600SemiBold' },
  sectionLabel: { fontSize: 11, fontFamily: 'Inter_700Bold', letterSpacing: 0.8 },
  help: { fontSize: 13, fontFamily: 'Inter_400Regular', lineHeight: 18 },
  mono: {
    fontSize: 12.5,
    fontFamily: Platform.select({ ios: 'Menlo', android: 'monospace', default: 'monospace' }),
    lineHeight: 19,
  },
  input: { borderWidth: 1, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, fontSize: 14, fontFamily: 'Inter_500Medium' },
  actions: { flexDirection: 'row', gap: 10 },
  btn: { flex: 1, paddingVertical: 12, borderRadius: 10, alignItems: 'center' },
  btnGhost: { flex: 0, paddingHorizontal: 18, borderWidth: 1 },
  btnText: { fontSize: 13, fontFamily: 'Inter_600SemiBold' },
  result: { fontSize: 13, fontFamily: 'Inter_500Medium', lineHeight: 18 },
});
