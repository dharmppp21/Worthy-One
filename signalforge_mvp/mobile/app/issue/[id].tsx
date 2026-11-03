import React, { useState } from 'react';
import {
  ActivityIndicator,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useQuery } from '@tanstack/react-query';
import { router, useLocalSearchParams } from 'expo-router';
import { Feather } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import { useColors } from '@/hooks/useColors';
import { relativeTime } from '@/lib/format';
import { useConnection } from '@/contexts/ConnectionContext';
import {
  decideRemediation,
  getIncident,
  getRemediation,
  getRootCause,
  SignalForgeError,
} from '@/lib/signalforge';

export default function IncidentDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const colors = useColors();
  const insets = useSafeAreaInsets();
  const { connection } = useConnection();
  const [working, setWorking] = useState(false);
  const [decisionError, setDecisionError] = useState<string | null>(null);

  const incidentQ = useQuery({
    queryKey: ['incident', id, connection.baseUrl],
    queryFn: () => getIncident(connection, id!),
    enabled: !!id,
  });
  const incident = incidentQ.data;

  const rootCauseQ = useQuery({
    queryKey: ['root-cause', incident?.service_name, connection.baseUrl],
    queryFn: () => getRootCause(connection, incident!.service_name),
    enabled: !!incident,
  });

  const remediationQ = useQuery({
    queryKey: ['remediation', id, connection.baseUrl],
    queryFn: () => getRemediation(connection, id!),
    enabled: !!id,
  });

  async function decide(approved: boolean) {
    if (!id) return;
    setWorking(true);
    setDecisionError(null);
    if (Platform.OS !== 'web') Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    try {
      await decideRemediation(connection, id, approved);
      await Promise.all([incidentQ.refetch(), remediationQ.refetch()]);
    } catch (e) {
      setDecisionError(e instanceof SignalForgeError ? e.message : 'Failed to record the decision.');
    } finally {
      setWorking(false);
    }
  }

  const top = rootCauseQ.data?.hypotheses?.[0];
  const remediation = remediationQ.data;
  const priorDecision = incident?.timeline
    ?.slice()
    .reverse()
    .find((e) => e.event_type === 'remediation');

  return (
    <View style={[styles.page, { backgroundColor: colors.background, paddingTop: insets.top }]}>
      <Pressable onPress={() => router.back()} style={styles.back}>
        <Feather name="chevron-left" size={22} color={colors.primary} />
        <Text style={[styles.backText, { color: colors.primary }]}>Incidents</Text>
      </Pressable>

      {incidentQ.isLoading || !incident ? (
        <View style={styles.centered}>
          <ActivityIndicator color={colors.primary} />
        </View>
      ) : (
        <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 40, gap: 16 }}>
          <View>
            <Text style={[styles.title, { color: colors.foreground }]}>{incident.title}</Text>
            <View style={styles.badgeRow}>
              <Badge colors={colors} text={incident.severity.toUpperCase()} tone="destructive" />
              <Badge colors={colors} text={incident.status} tone="muted" />
              <Text style={[styles.time, { color: colors.mutedForeground }]}>
                {relativeTime(incident.created_at)}
              </Text>
            </View>
          </View>

          <Section colors={colors} label="Summary">
            <Text style={[styles.body, { color: colors.foreground }]}>{incident.summary}</Text>
            <Text style={[styles.service, { color: colors.mutedForeground }]}>{incident.service_name}</Text>
          </Section>

          {/* Root cause */}
          <Section colors={colors} label="Root cause">
            {rootCauseQ.isLoading ? (
              <ActivityIndicator color={colors.primary} />
            ) : top ? (
              <View style={[styles.card, { backgroundColor: colors.card, borderColor: colors.border }]}>
                <View style={styles.rcHead}>
                  <Text style={[styles.rcService, { color: colors.foreground }]}>{top.service_name}</Text>
                  <View style={[styles.conf, { backgroundColor: colors.primary + '22' }]}>
                    <Text style={[styles.confText, { color: colors.primary }]}>{top.confidence} · {top.total_score}/100</Text>
                  </View>
                </View>
                <Text style={[styles.recommend, { color: colors.foreground }]}>
                  <Text style={{ fontFamily: 'Inter_700Bold' }}>Recommended: </Text>
                  {top.recommended_action}
                </Text>
                <View style={{ gap: 6, marginTop: 6 }}>
                  {top.evidence
                    .filter((e) => e.score > 0)
                    .map((e, i) => (
                      <View key={i} style={styles.evidenceRow}>
                        <Text style={[styles.evType, { color: colors.mutedForeground }]}>{e.type}</Text>
                        <Text style={[styles.evScore, { color: colors.success }]}>+{e.score}</Text>
                        <Text style={[styles.evReason, { color: colors.foreground }]}>{e.reason}</Text>
                      </View>
                    ))}
                </View>
              </View>
            ) : (
              <Text style={[styles.hint, { color: colors.mutedForeground }]}>No root-cause hypotheses yet.</Text>
            )}
          </Section>

          {/* Remediation */}
          {remediation && (
            <Section colors={colors} label="Remediation">
              {remediation.action === 'rollback' ? (
                <View style={[styles.card, { backgroundColor: '#1E150633', borderColor: colors.warning }]}>
                  <View style={styles.rcHead}>
                    <Text style={[styles.rollback, { color: colors.warning }]}>
                      ROLLBACK  v{remediation.from_version} → v{remediation.to_version ?? 'previous'}
                    </Text>
                  </View>
                  <Text style={[styles.body, { color: colors.foreground }]}>{remediation.summary}</Text>
                  {priorDecision ? (
                    <Text style={[styles.decided, { color: colors.success }]}>✓ {priorDecision.message}</Text>
                  ) : (
                    <View style={styles.actions}>
                      <Pressable
                        disabled={working}
                        onPress={() => decide(true)}
                        style={[styles.btn, { backgroundColor: colors.warning }, working && { opacity: 0.5 }]}
                      >
                        <Text style={[styles.btnText, { color: '#1A1205' }]}>
                          {working ? 'Working…' : 'Approve rollback'}
                        </Text>
                      </Pressable>
                      <Pressable
                        disabled={working}
                        onPress={() => decide(false)}
                        style={[styles.btn, styles.btnGhost, { borderColor: colors.border }, working && { opacity: 0.5 }]}
                      >
                        <Text style={[styles.btnText, { color: colors.foreground }]}>Reject</Text>
                      </Pressable>
                    </View>
                  )}
                  {decisionError && <Text style={[styles.errorText, { color: colors.destructive }]}>{decisionError}</Text>}
                </View>
              ) : (
                <Text style={[styles.hint, { color: colors.mutedForeground }]}>{remediation.summary}</Text>
              )}
            </Section>
          )}

          {/* Timeline */}
          <Section colors={colors} label="Timeline">
            <View style={{ gap: 10 }}>
              {incident.timeline.map((entry, i) => (
                <View key={i} style={styles.timelineRow}>
                  <View style={[styles.tlDot, { backgroundColor: colors.primary }]} />
                  <View style={{ flex: 1 }}>
                    <Text style={[styles.tlMsg, { color: colors.foreground }]}>{entry.message}</Text>
                    <Text style={[styles.tlMeta, { color: colors.mutedForeground }]}>
                      {entry.actor} · {relativeTime(entry.timestamp)}
                    </Text>
                  </View>
                </View>
              ))}
            </View>
          </Section>
        </ScrollView>
      )}
    </View>
  );
}

function Section({
  colors,
  label,
  children,
}: {
  colors: ReturnType<typeof useColors>;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <View style={{ gap: 8 }}>
      <Text style={[styles.sectionLabel, { color: colors.mutedForeground }]}>{label.toUpperCase()}</Text>
      {children}
    </View>
  );
}

function Badge({
  colors,
  text,
  tone,
}: {
  colors: ReturnType<typeof useColors>;
  text: string;
  tone: 'destructive' | 'muted';
}) {
  const fg = tone === 'destructive' ? colors.destructive : colors.mutedForeground;
  const bg = tone === 'destructive' ? colors.destructive + '22' : colors.muted;
  return (
    <View style={[styles.badge, { backgroundColor: bg }]}>
      <Text style={[styles.badgeText, { color: fg }]}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1 },
  back: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 10, paddingVertical: 8 },
  backText: { fontSize: 16, fontFamily: 'Inter_500Medium' },
  centered: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  title: { fontSize: 22, fontFamily: 'Inter_700Bold', lineHeight: 28 },
  badgeRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 10 },
  badge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6 },
  badgeText: { fontSize: 11, fontFamily: 'Inter_700Bold', letterSpacing: 0.3 },
  time: { fontSize: 12, fontFamily: 'Inter_400Regular', marginLeft: 'auto' },
  sectionLabel: { fontSize: 11, fontFamily: 'Inter_700Bold', letterSpacing: 0.8 },
  body: { fontSize: 14, fontFamily: 'Inter_400Regular', lineHeight: 20 },
  service: { fontSize: 12, fontFamily: 'Inter_500Medium', marginTop: 6 },
  card: { borderWidth: 1, borderRadius: 12, padding: 14, gap: 10 },
  rcHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  rcService: { fontSize: 15, fontFamily: 'Inter_600SemiBold' },
  conf: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6 },
  confText: { fontSize: 12, fontFamily: 'Inter_600SemiBold' },
  recommend: { fontSize: 14, fontFamily: 'Inter_400Regular', lineHeight: 20 },
  evidenceRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 8 },
  evType: { width: 76, fontSize: 12, fontFamily: 'Inter_600SemiBold' },
  evScore: { width: 34, fontSize: 12, fontFamily: 'Inter_700Bold' },
  evReason: { flex: 1, fontSize: 12, fontFamily: 'Inter_400Regular', lineHeight: 17 },
  rollback: { fontSize: 13, fontFamily: 'Inter_700Bold', letterSpacing: 0.3 },
  decided: { fontSize: 13, fontFamily: 'Inter_600SemiBold' },
  actions: { flexDirection: 'row', gap: 10 },
  btn: { flex: 1, paddingVertical: 11, borderRadius: 8, alignItems: 'center' },
  btnGhost: { borderWidth: 1 },
  btnText: { fontSize: 14, fontFamily: 'Inter_600SemiBold' },
  errorText: { fontSize: 12, fontFamily: 'Inter_500Medium' },
  hint: { fontSize: 13, fontFamily: 'Inter_400Regular' },
  timelineRow: { flexDirection: 'row', gap: 10 },
  tlDot: { width: 8, height: 8, borderRadius: 4, marginTop: 5 },
  tlMsg: { fontSize: 13, fontFamily: 'Inter_400Regular', lineHeight: 18 },
  tlMeta: { fontSize: 11, fontFamily: 'Inter_400Regular', marginTop: 2 },
});
