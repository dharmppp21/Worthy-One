import React, { useEffect } from 'react';
import { Platform, StyleSheet, View } from 'react-native';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import colors from '@/constants/colors';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { KeyboardProvider } from 'react-native-keyboard-controller';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import {
  Inter_400Regular,
  Inter_500Medium,
  Inter_600SemiBold,
  Inter_700Bold,
  useFonts,
} from '@expo-google-fonts/inter';
import { Stack } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { ConnectionProvider } from '@/contexts/ConnectionContext';

SplashScreen.preventAutoHideAsync();

const queryClient = new QueryClient();

/**
 * Constrain the phone layout to a centred column on wide (web) viewports so a
 * 26px heading doesn't stretch across 1900px.
 */
const CONTENT_WIDTH = 640;

const styles = StyleSheet.create({
  page: {
    flex: 1,
    backgroundColor: colors.dark.background,
  },
  shell: {
    flex: 1,
    width: '100%',
    ...Platform.select({
      web: { maxWidth: CONTENT_WIDTH, alignSelf: 'center' },
      default: {},
    }),
  },
});

export default function RootLayout() {
  const [fontsLoaded, fontError] = useFonts({
    Inter_400Regular,
    Inter_500Medium,
    Inter_600SemiBold,
    Inter_700Bold,
  });

  useEffect(() => {
    if (fontsLoaded || fontError) {
      SplashScreen.hideAsync();
    }
  }, [fontsLoaded, fontError]);

  if (!fontsLoaded && !fontError) return null;

  return (
    <SafeAreaProvider>
      <ErrorBoundary>
        <QueryClientProvider client={queryClient}>
          <ConnectionProvider>
            <GestureHandlerRootView>
              <KeyboardProvider>
                <View style={styles.page}>
                  <View style={styles.shell}>
                    <Stack screenOptions={{ headerShown: false }}>
                      <Stack.Screen name="(tabs)" />
                      <Stack.Screen name="issue/[id]" />
                    </Stack>
                  </View>
                </View>
              </KeyboardProvider>
            </GestureHandlerRootView>
          </ConnectionProvider>
        </QueryClientProvider>
      </ErrorBoundary>
    </SafeAreaProvider>
  );
}
