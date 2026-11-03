import React, { createContext, useContext, useEffect, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import type { Connection } from '@/lib/signalforge';

const STORAGE_KEY = '@signalforge:connection';

/**
 * Default connection. Points at the live demo so the app works on first launch;
 * override in Settings (or via EXPO_PUBLIC_SIGNALFORGE_* at build time) to aim
 * it at your own SignalForge deployment.
 */
const DEFAULT_CONNECTION: Connection = {
  baseUrl:
    process.env.EXPO_PUBLIC_SIGNALFORGE_URL ??
    'https://decades-college-logo-gratis.trycloudflare.com/api',
  apiKey: process.env.EXPO_PUBLIC_SIGNALFORGE_KEY ?? 'sf-api-key-demo',
  tenant: process.env.EXPO_PUBLIC_SIGNALFORGE_TENANT ?? 'demo-company',
};

type ConnectionContextValue = {
  connection: Connection;
  setConnection: (c: Connection) => Promise<void>;
  loading: boolean;
};

const ConnectionContext = createContext<ConnectionContextValue | null>(null);

export function ConnectionProvider({ children }: { children: React.ReactNode }) {
  const [connection, setConn] = useState<Connection>(DEFAULT_CONNECTION);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    AsyncStorage.getItem(STORAGE_KEY)
      .then((raw) => {
        if (raw) {
          try {
            setConn({ ...DEFAULT_CONNECTION, ...JSON.parse(raw) });
          } catch {
            // Corrupt stored value — fall back to the default.
          }
        }
      })
      .finally(() => setLoading(false));
  }, []);

  async function setConnection(c: Connection) {
    setConn(c);
    try {
      await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(c));
    } catch {
      // Non-fatal: the in-memory value still updates for this session.
    }
  }

  return (
    <ConnectionContext.Provider value={{ connection, setConnection, loading }}>
      {children}
    </ConnectionContext.Provider>
  );
}

export function useConnection(): ConnectionContextValue {
  const ctx = useContext(ConnectionContext);
  if (!ctx) throw new Error('useConnection must be used within ConnectionProvider');
  return ctx;
}
