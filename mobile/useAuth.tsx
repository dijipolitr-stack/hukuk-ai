// hooks/useAuth.tsx — Kimlik doğrulama context ve hook

import React, {
  createContext, useContext, useEffect, useState, useCallback,
} from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { AuthAPI, TokenStore, LoginResponse } from '../services/api';

interface LawyerInfo {
  id:        number;
  name:      string;
  email:     string;
}

interface AuthContextValue {
  lawyer:    LawyerInfo | null;
  isLoading: boolean;
  login:     (email: string, password: string) => Promise<void>;
  logout:    () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [lawyer,    setLawyer]    = useState<LawyerInfo | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Uygulama açılışında kayıtlı oturumu kontrol et
  useEffect(() => {
    (async () => {
      try {
        const [token, raw] = await AsyncStorage.multiGet(['access_token', 'lawyer_info']);
        if (token[1] && raw[1]) {
          setLawyer(JSON.parse(raw[1]));
        }
      } finally {
        setIsLoading(false);
      }
    })();
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const res: LoginResponse = await AuthAPI.login(email, password);
    const info: LawyerInfo   = { id: res.lawyer_id, name: res.full_name, email };
    await TokenStore.set(res.access_token);
    await AsyncStorage.setItem('lawyer_info', JSON.stringify(info));
    setLawyer(info);
  }, []);

  const logout = useCallback(async () => {
    await TokenStore.clear();
    setLawyer(null);
  }, []);

  return (
    <AuthContext.Provider value={{ lawyer, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
