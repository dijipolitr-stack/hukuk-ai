// navigation/AppNavigator.tsx — Uygulama navigasyon yapısı

import React from 'react';
import { View, ActivityIndicator } from 'react-native';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';

import { AuthProvider, useAuth } from '../hooks/useAuth';
import { Colors, Typography } from '../theme';

import LoginScreen          from '../screens/LoginScreen';
import HomeScreen           from '../screens/HomeScreen';
import NewPetitionScreen    from '../screens/NewPetitionScreen';
import PetitionDetailScreen from '../screens/PetitionDetailScreen';

export type RootStackParamList = {
  Login:           undefined;
  Home:            undefined;
  NewPetition:     { petitionType: string };
  PetitionDetail:  { petitionId: number };
};

const Stack = createNativeStackNavigator<RootStackParamList>();

function RootNavigator() {
  const { lawyer, isLoading } = useAuth();

  if (isLoading) {
    return (
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: Colors.background }}>
        <ActivityIndicator size="large" color={Colors.primary} />
      </View>
    );
  }

  return (
    <Stack.Navigator
      screenOptions={{
        headerStyle:       { backgroundColor: Colors.surface },
        headerTintColor:   Colors.primary,
        headerTitleStyle:  { ...Typography.h3, fontSize: 16 },
        headerShadowVisible: false,
        contentStyle:      { backgroundColor: Colors.background },
      }}
    >
      {!lawyer ? (
        // Giriş yapılmamış
        <Stack.Screen
          name="Login"
          component={LoginScreen}
          options={{ headerShown: false }}
        />
      ) : (
        // Giriş yapılmış
        <>
          <Stack.Screen
            name="Home"
            component={HomeScreen}
            options={{ title: 'Hukuk AI', headerShown: false }}
          />
          <Stack.Screen
            name="NewPetition"
            component={NewPetitionScreen}
            options={({ route }) => ({
              title: 'Yeni Dilekçe',
              headerBackTitle: 'Geri',
            })}
          />
          <Stack.Screen
            name="PetitionDetail"
            component={PetitionDetailScreen}
            options={{ title: 'Dilekçe Detayı', headerBackTitle: 'Geri' }}
          />
        </>
      )}
    </Stack.Navigator>
  );
}

export default function AppNavigator() {
  return (
    <AuthProvider>
      <NavigationContainer>
        <RootNavigator />
      </NavigationContainer>
    </AuthProvider>
  );
}
