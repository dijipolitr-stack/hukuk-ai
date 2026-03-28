// screens/LoginScreen.tsx — Avukat giriş ekranı

import React, { useState } from 'react';
import {
  View, Text, TextInput, TouchableOpacity,
  StyleSheet, KeyboardAvoidingView, Platform,
  ScrollView, ActivityIndicator, Alert,
} from 'react-native';
import { Colors, Typography, Spacing, Radius, Shadow } from '../theme';
import { useAuth } from '../hooks/useAuth';

export default function LoginScreen() {
  const { login } = useAuth();

  const [email,     setEmail]     = useState('');
  const [password,  setPassword]  = useState('');
  const [loading,   setLoading]   = useState(false);
  const [showPass,  setShowPass]  = useState(false);

  const handleLogin = async () => {
    if (!email.trim() || !password) {
      Alert.alert('Eksik bilgi', 'E-posta ve şifre zorunludur.');
      return;
    }
    setLoading(true);
    try {
      await login(email.trim().toLowerCase(), password);
    } catch (e: any) {
      Alert.alert('Giriş başarısız', e.message ?? 'Bir hata oluştu.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.flex}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView
        contentContainerStyle={styles.container}
        keyboardShouldPersistTaps="handled"
      >
        {/* Logo / Başlık */}
        <View style={styles.header}>
          <View style={styles.logoCircle}>
            <Text style={styles.logoText}>⚖</Text>
          </View>
          <Text style={styles.appName}>Hukuk AI</Text>
          <Text style={styles.tagline}>Akıllı Dilekçe Asistanı</Text>
        </View>

        {/* Form Kartı */}
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Avukat Girişi</Text>

          <View style={styles.fieldGroup}>
            <Text style={styles.label}>E-POSTA</Text>
            <TextInput
              style={styles.input}
              value={email}
              onChangeText={setEmail}
              placeholder="av@baronuz.com"
              placeholderTextColor={Colors.textTertiary}
              keyboardType="email-address"
              autoCapitalize="none"
              autoCorrect={false}
              returnKeyType="next"
            />
          </View>

          <View style={styles.fieldGroup}>
            <Text style={styles.label}>ŞİFRE</Text>
            <View style={styles.passwordRow}>
              <TextInput
                style={[styles.input, styles.passwordInput]}
                value={password}
                onChangeText={setPassword}
                placeholder="••••••••"
                placeholderTextColor={Colors.textTertiary}
                secureTextEntry={!showPass}
                returnKeyType="done"
                onSubmitEditing={handleLogin}
              />
              <TouchableOpacity
                style={styles.eyeBtn}
                onPress={() => setShowPass(v => !v)}
              >
                <Text style={styles.eyeIcon}>{showPass ? '🙈' : '👁'}</Text>
              </TouchableOpacity>
            </View>
          </View>

          <TouchableOpacity
            style={[styles.loginBtn, loading && styles.loginBtnDisabled]}
            onPress={handleLogin}
            disabled={loading}
            activeOpacity={0.85}
          >
            {loading
              ? <ActivityIndicator color={Colors.textOnPrimary} />
              : <Text style={styles.loginBtnText}>Giriş Yap</Text>
            }
          </TouchableOpacity>

          <TouchableOpacity style={styles.forgotBtn}>
            <Text style={styles.forgotText}>Şifremi unuttum</Text>
          </TouchableOpacity>
        </View>

        {/* Alt bilgi */}
        <Text style={styles.footer}>
          Türkiye Barolar Birliği üyesi avukatlara özeldir.{'\n'}
          Hesabınız yoksa sistem yöneticinizle iletişime geçin.
        </Text>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex:       { flex: 1, backgroundColor: Colors.background },
  container:  { flexGrow: 1, justifyContent: 'center', padding: Spacing.lg },

  header: {
    alignItems: 'center',
    marginBottom: Spacing.xl,
  },
  logoCircle: {
    width:           72,
    height:          72,
    borderRadius:    36,
    backgroundColor: Colors.primary,
    alignItems:      'center',
    justifyContent:  'center',
    marginBottom:    Spacing.md,
    ...Shadow.md,
  },
  logoText:  { fontSize: 32 },
  appName:   { ...Typography.h1, color: Colors.primary, marginBottom: 4 },
  tagline:   { ...Typography.small, color: Colors.textSecondary },

  card: {
    backgroundColor: Colors.surface,
    borderRadius:    Radius.lg,
    padding:         Spacing.lg,
    marginBottom:    Spacing.lg,
    ...Shadow.md,
  },
  cardTitle: {
    ...Typography.h3,
    marginBottom: Spacing.lg,
    textAlign:    'center',
    color:        Colors.textSecondary,
  },

  fieldGroup:   { marginBottom: Spacing.md },
  label:        { ...Typography.label, marginBottom: Spacing.xs },
  input: {
    backgroundColor: Colors.background,
    borderWidth:     1,
    borderColor:     Colors.border,
    borderRadius:    Radius.md,
    paddingHorizontal: Spacing.md,
    paddingVertical:   12,
    fontSize:        15,
    color:           Colors.textPrimary,
  },
  passwordRow:  { flexDirection: 'row', alignItems: 'center' },
  passwordInput:{ flex: 1, marginRight: Spacing.sm },
  eyeBtn: {
    padding:         10,
    backgroundColor: Colors.background,
    borderWidth:     1,
    borderColor:     Colors.border,
    borderRadius:    Radius.md,
  },
  eyeIcon: { fontSize: 16 },

  loginBtn: {
    backgroundColor: Colors.primary,
    borderRadius:    Radius.md,
    paddingVertical: 15,
    alignItems:      'center',
    marginTop:       Spacing.sm,
    ...Shadow.sm,
  },
  loginBtnDisabled: { opacity: 0.7 },
  loginBtnText: {
    color:      Colors.textOnPrimary,
    fontSize:   16,
    fontWeight: '600',
  },

  forgotBtn:  { alignItems: 'center', marginTop: Spacing.md },
  forgotText: { ...Typography.small, color: Colors.primary },

  footer: {
    ...Typography.small,
    textAlign:  'center',
    color:      Colors.textTertiary,
    lineHeight: 19,
  },
});
