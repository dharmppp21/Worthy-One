import React from 'react';
import {
  ActivityIndicator,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';
import * as Haptics from 'expo-haptics';
import { useColors } from '@/hooks/useColors';
import { relativeTime } from '@/lib/format';
import { useConnection } from '@/contexts/ConnectionContext';
import { listIncidents, type Incident, type Severity } from '@/lib/signalforge';

const SEVERITY_META: Record<Severity, { label: string; key: 'destructive' | 'warning' | 'primary' }> = {
  critical: { label: 'CRITICAL', key: 'destructive' },
  warning: { label: 'WARNING', key: 'warning' },
  info: { label: 'INFO', key: 'primary' },
};

export default function IncidentsScreen() {
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const { connection } = useConnection();

  const { data, isLoading, isError, error, refetch, isRefetching } = useQuery({
    queryKey: ['incidents', connection.baseUrl, connection.apiKey],
    queryFn: () => listIncidents(connection),
    refetchInterval: 15000,
  });

  const incidents = data ?? [];
  const criticalCount = incidents.filter((i) => i.severity === 'critical').length;
  const warningCount = incidents.filter((i) => i.severity === 'warning').length;

  function openIncident(id: string) {
    if (Platform.OS !== 'web') Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    router.push(`/issue/${encodeURIComponent(id)}`);
  }

  return (
    <View style={[styles.page, { backgroundColor: colors.background, paddingTop: insets.top }]}>
      <View style={styles.header}>
        <Text style={[styles.brand, { color: colors.mutedForeground }]}>SIGNALFORGE</Text>
        <Text style={[styles.title, { color: colors.foreground }]}>Incidents</Text>
        <View style={styles.statRow}>
          <Stat colors={colors} value={incidents.length} label="OPEN" tone="foreground" />
          <Stat colors={colors} value={criticalCount} label="CRITICAL" tone="destructive" />
          <Stat colors={colors} value={warningCount} label="WARNING" tone="warning" />
        </View>
      </View>

      <ScrollView
        contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 100, gap: 10 }}
        refreshControl={
          <RefreshControl refreshing={isRefetching} onRefresh={refetch} tintColor={colors.primary} />
        }
      >
        {isLoading ? (
          <View style={styles.centered}>
            <ActivityIndicator color={colors.primary} />
            <Text style={[styles.hint, { color: colors.mutedForeground }]}>Loading incidents…</Text>
          </View>
        ) : isError ? (
          <View style={styles.centered}>
            <Text style={[styles.errorText, { color: colors.destructive }]}>
              {error instanceof Error ? error.message : 'Could not reach SignalForge.'}
            </Text>
            <Text style={[styles.hint, { color: colors.mutedForeground }]}>
              Check the connection in Settings, then pull to retry.
            </Text>
          </View>
        ) : incidents.length === 0 ? (
          <View style={styles.centered}>
            <Text style={[styles.emptyTitle, { color: colors.foreground }]}>All clear</Text>
            <Text style={[styles.hint, { color: colors.mutedForeground }]}>
              No open incidents. Send test traffic from the Connect tab to create one.
            </Text>
          </View>
        ) : (
          incidents.map((incident) => (
            <IncidentRow key={incident.id} incident={incident} colors={colors} onPress={openIncident} />
          ))
        )}
      </ScrollView>
    </View>
  );
}

function Stat({
  colors,
  value,
  label,
  tone,
}: {
  colors: ReturnType<typeof useColors>;
  value: number;
  label: string;
  tone: 'foreground' | 'destructive' | 'warning';
}) {
  return (
    <View style={[styles.stat, { backgroundColor: colors.card, borderColor: colors.border }]}>
      <Text style={[styles.statValue, { color: colors[tone] }]}>{value}</Text>
      <Text style={[styles.statLabel, { color: colors.mutedForeground }]}>{label}</Text>
    </View>
  );
}

function IncidentRow({
  incident,
  colors,
  onPress,
}: {
  incident: Incident;
  colors: ReturnType<typeof useColors>;
  onPress: (id: string) => void;
}) {
  const meta = SEVERITY_META[incident.severity] ?? SEVERITY_META.info;
  const accent = colors[meta.key];
  return (
    <Pressable
      onPress={() => onPress(incident.id)}
      style={({ pressed }) => [
        styles.row,
        { backgroundColor: colors.card, borderColor: colors.border },
        pressed && { opacity: 0.75 },
      ]}
    >
      <View style={[styles.accent, { backgroundColor: accent }]} />
      <View style={{ flex: 1, padding: 14, gap: 8 }}>
        <View style={styles.badgeRow}>
          <View style={[styles.sevBadge, { backgroundColor: accent + '22' }]}>
            <View style={[styles.dot, { backgroundColor: accent }]} />
            <Text style={[styles.sevText, { color: accent }]}>{meta.label}</Text>
          </View>
          <View style={[styles.statusPill, { backgroundColor: colors.muted }]}>
            <Text style={[styles.statusText, { color: colors.mutedForeground }]}>{incident.status}</Text>
          </View>
          <Text style={[styles.time, { color: colors.mutedForeground }]}>
            {relativeTime(incident.created_at)}
          </Text>
        </View>
        <Text style={[styles.rowTitle, { color: colors.foreground }]} numberOfLines={2}>
          {incident.title}
        </Text>
        <Text style={[styles.service, { color: colors.mutedForeground }]}>{incident.service_name}</Text>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1 },
  header: { paddingHorizontal: 16, paddingTop: 12, paddingBottom: 4 },
  brand: { fontSize: 11, fontFamily: 'Inter_700Bold', letterSpacing: 1.5 },
  title: { fontSize: 28, fontFamily: 'Inter_700Bold', marginTop: 2 },
  statRow: { flexDirection: 'row', gap: 10, marginTop: 14 },
  stat: { flex: 1, borderWidth: 1, borderRadius: 10, paddingVertical: 10, alignItems: 'center' },
  statValue: { fontSize: 22, fontFamily: 'Inter_700Bold' },
  statLabel: { fontSize: 10, fontFamily: 'Inter_600SemiBold', letterSpacing: 0.5, marginTop: 2 },
  centered: { alignItems: 'center', gap: 8, paddingVertical: 48 },
  hint: { fontSize: 13, fontFamily: 'Inter_400Regular', textAlign: 'center', paddingHorizontal: 24 },
  errorText: { fontSize: 14, fontFamily: 'Inter_600SemiBold', textAlign: 'center' },
  emptyTitle: { fontSize: 18, fontFamily: 'Inter_600SemiBold' },
  row: { flexDirection: 'row', borderWidth: 1, borderRadius: 12, overflow: 'hidden' },
  accent: { width: 4 },
  badgeRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  sevBadge: { flexDirection: 'row', alignItems: 'center', gap: 5, paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6 },
  dot: { width: 6, height: 6, borderRadius: 3 },
  sevText: { fontSize: 11, fontFamily: 'Inter_700Bold', letterSpacing: 0.3 },
  statusPill: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6 },
  statusText: { fontSize: 11, fontFamily: 'Inter_500Medium' },
  time: { fontSize: 11, fontFamily: 'Inter_400Regular', marginLeft: 'auto' },
  rowTitle: { fontSize: 15, fontFamily: 'Inter_600SemiBold', lineHeight: 20 },
  service: { fontSize: 12, fontFamily: 'Inter_500Medium' },
});
