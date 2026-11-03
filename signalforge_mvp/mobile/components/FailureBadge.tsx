import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

interface FailureBadgeConfig {
  label: string;
  bg: string;
  fg: string;
  dot: string;
}

const BADGE_CONFIG: Record<string, FailureBadgeConfig> = {
  malformed_tool_call: { label: 'Malformed Tool Call', bg: '#2D1E0A', fg: '#F5A520', dot: '#F5A520' },
  schema_validation:   { label: 'Schema Validation',  bg: '#1E0D30', fg: '#A78BFA', dot: '#A78BFA' },
  max_iterations:      { label: 'Max Iterations',     bg: '#2D0A0A', fg: '#F04D4D', dot: '#F04D4D' },
  context_overflow:    { label: 'Context Overflow',   bg: '#0A1A2D', fg: '#60A5FA', dot: '#60A5FA' },
  empty_response:      { label: 'Empty Response',     bg: '#1A1A24', fg: '#9090B0', dot: '#9090B0' },
  tool_timeout:        { label: 'Tool Timeout',       bg: '#2D1A0A', fg: '#FB923C', dot: '#FB923C' },
};

const NEUTRAL = { bg: '#1A1A24', fg: '#9090B0', dot: '#9090B0' };

/** `some_new_class` -> `Some New Class` */
function humanize(failureClass: string): string {
  return failureClass
    .split(/[_\-\s]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

/**
 * failureClass is an open set — an agent can declare its own — so anything the
 * palette doesn't know renders in neutral grey rather than crashing on an
 * undefined config.
 */
function configFor(failureClass: string): FailureBadgeConfig {
  return (
    BADGE_CONFIG[failureClass] ?? { ...NEUTRAL, label: humanize(failureClass) || 'Unknown' }
  );
}

export function failureColor(failureClass: string): string {
  return configFor(failureClass).dot;
}

interface Props {
  failureClass: string;
  size?: 'sm' | 'md';
}

export default function FailureBadge({ failureClass, size = 'md' }: Props) {
  const cfg = configFor(failureClass);
  const isSmall = size === 'sm';

  return (
    <View style={[styles.badge, { backgroundColor: cfg.bg }, isSmall && styles.badgeSm]}>
      <View style={[styles.dot, { backgroundColor: cfg.dot }, isSmall && styles.dotSm]} />
      <Text style={[styles.label, { color: cfg.fg }, isSmall && styles.labelSm]}>
        {cfg.label}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 6,
    gap: 5,
    alignSelf: 'flex-start',
  },
  badgeSm: {
    paddingHorizontal: 6,
    paddingVertical: 3,
    borderRadius: 4,
  },
  dot: {
    width: 6,
    height: 6,
    borderRadius: 3,
  },
  dotSm: {
    width: 5,
    height: 5,
  },
  label: {
    fontSize: 12,
    fontFamily: 'Inter_600SemiBold',
    letterSpacing: 0.1,
  },
  labelSm: {
    fontSize: 11,
  },
});
