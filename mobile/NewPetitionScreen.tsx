// screens/NewPetitionScreen.tsx — Sesli ve yazılı talep girişi

import React, { useState, useRef, useCallback } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, ScrollView,
  StyleSheet, Alert, Animated, ActivityIndicator,
  KeyboardAvoidingView, Platform,
} from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { Audio } from 'expo-av';
import { Colors, Typography, Spacing, Radius, Shadow, PETITION_TYPES } from '../theme';
import { PetitionAPI } from '../services/api';
import { useAuth } from '../hooks/useAuth';

type InputMode = 'text' | 'voice';

export default function NewPetitionScreen() {
  const navigation = useNavigation<any>();
  const route      = useRoute<any>();
  const { lawyer } = useAuth();

  const petitionType = route.params?.petitionType ?? 'mahkeme';
  const typeInfo     = PETITION_TYPES.find(t => t.key === petitionType)!;

  const [inputMode,      setInputMode]      = useState<InputMode>('text');
  const [talep,          setTalep]          = useState('');
  const [extraContext,   setExtraContext]    = useState('');
  const [categoryHint,   setCategoryHint]   = useState('');
  const [useHaiku,       setUseHaiku]       = useState(false);
  const [generating,     setGenerating]     = useState(false);
  const [generatedText,  setGeneratedText]  = useState('');
  const [usedDecrees,    setUsedDecrees]    = useState<any[]>([]);
  const [petitionId,     setPetitionId]     = useState<number | null>(null);
  const [warning,        setWarning]        = useState('');
  const [costInfo,       setCostInfo]       = useState('');

  // Ses kaydı
  const [recording,      setRecording]      = useState<Audio.Recording | null>(null);
  const [isRecording,    setIsRecording]    = useState(false);
  const [transcribing,   setTranscribing]   = useState(false);
  const pulseAnim = useRef(new Animated.Value(1)).current;

  // ── Ses kaydı ─────────────────────────────────────────────────────────────

  const startRecording = async () => {
    try {
      const perm = await Audio.requestPermissionsAsync();
      if (!perm.granted) {
        Alert.alert('İzin gerekli', 'Sesli talep için mikrofon iznine ihtiyaç var.');
        return;
      }
      await Audio.setAudioModeAsync({
        allowsRecordingIOS:     true,
        playsInSilentModeIOS:   true,
      });
      const { recording: rec } = await Audio.Recording.createAsync(
        Audio.RecordingOptionsPresets.HIGH_QUALITY
      );
      setRecording(rec);
      setIsRecording(true);

      // Nabız animasyonu
      Animated.loop(
        Animated.sequence([
          Animated.timing(pulseAnim, { toValue: 1.15, duration: 600, useNativeDriver: true }),
          Animated.timing(pulseAnim, { toValue: 1.0,  duration: 600, useNativeDriver: true }),
        ])
      ).start();
    } catch (e) {
      Alert.alert('Kayıt başlatılamadı', String(e));
    }
  };

  const stopRecording = async () => {
    if (!recording) return;
    pulseAnim.stopAnimation();
    pulseAnim.setValue(1);
    setIsRecording(false);

    try {
      await recording.stopAndUnloadAsync();
      const uri = recording.getURI();
      setRecording(null);

      if (!uri) return;
      setTranscribing(true);
      const text = await PetitionAPI.transcribeAudio(uri);
      setTalep(prev => (prev ? prev + ' ' + text : text));
      setTranscribing(false);
    } catch (e: any) {
      setTranscribing(false);
      Alert.alert('Transkripsiyon hatası', e.message);
    }
  };

  // ── Dilekçe üretimi ───────────────────────────────────────────────────────

  const handleGenerate = useCallback(async () => {
    if (talep.trim().length < 20) {
      Alert.alert('Yetersiz bilgi', 'Lütfen en az 20 karakter talep girin.');
      return;
    }

    setGenerating(true);
    setGeneratedText('');
    setUsedDecrees([]);
    setWarning('');
    setCostInfo('');

    try {
      await PetitionAPI.generateStream(
        {
          petition_type:  petitionType,
          talep:          talep.trim(),
          category_hint:  categoryHint || undefined,
          use_haiku:      useHaiku,
          extra_context:  extraContext,
        },
        (chunk) => setGeneratedText(prev => prev + chunk),
        (meta)  => setUsedDecrees(meta.used_decrees),
        (msg)   => setWarning(msg),
        (done)  => {
          setPetitionId(done.petition_id);
          setCostInfo(`$${done.cost_usd.toFixed(4)}`);
          setGenerating(false);
        },
        (err)   => {
          Alert.alert('Hata', err);
          setGenerating(false);
        },
      );
    } catch (e: any) {
      Alert.alert('Bağlantı hatası', e.message);
      setGenerating(false);
    }
  }, [talep, petitionType, categoryHint, useHaiku, extraContext]);

  const handleViewPetition = () => {
    if (!petitionId) return;
    navigation.navigate('PetitionDetail', { petitionId });
  };

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <KeyboardAvoidingView
      style={styles.flex}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView
        style={styles.screen}
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled"
      >
        {/* Tür başlığı */}
        <View style={[styles.typeHeader, { backgroundColor: typeInfo.color + '15' }]}>
          <Text style={styles.typeEmoji}>{typeInfo.icon}</Text>
          <View>
            <Text style={[styles.typeName, { color: typeInfo.color }]}>{typeInfo.label}</Text>
            <Text style={styles.typeDesc}>{typeInfo.description}</Text>
          </View>
        </View>

        {/* Giriş modu seçimi */}
        <View style={styles.modeToggle}>
          {(['text', 'voice'] as InputMode[]).map(mode => (
            <TouchableOpacity
              key={mode}
              style={[styles.modeBtn, inputMode === mode && styles.modeBtnActive]}
              onPress={() => setInputMode(mode)}
            >
              <Text style={[styles.modeBtnText, inputMode === mode && styles.modeBtnTextActive]}>
                {mode === 'text' ? '⌨️  Yazarak' : '🎤  Sesle'}
              </Text>
            </TouchableOpacity>
          ))}
        </View>

        {/* Sesli giriş */}
        {inputMode === 'voice' && (
          <View style={styles.voiceSection}>
            <Animated.View style={[styles.micWrap, { transform: [{ scale: pulseAnim }] }]}>
              <TouchableOpacity
                style={[styles.micBtn, isRecording && styles.micBtnActive]}
                onPress={isRecording ? stopRecording : startRecording}
              >
                <Text style={styles.micIcon}>{isRecording ? '⏹' : '🎤'}</Text>
              </TouchableOpacity>
            </Animated.View>
            <Text style={styles.micHint}>
              {transcribing
                ? 'Ses yazıya çevriliyor...'
                : isRecording
                  ? 'Kaydediliyor... Durdurmak için dokun'
                  : 'Başlatmak için mikrofona dokun'}
            </Text>
            {transcribing && (
              <ActivityIndicator color={Colors.primary} style={{ marginTop: Spacing.sm }} />
            )}
          </View>
        )}

        {/* Talep alanı */}
        <View style={styles.section}>
          <Text style={styles.label}>
            {inputMode === 'voice' ? 'TRANSKRIPT / DÜZENLE' : 'TALEBİNİZİ YAZIN'}
          </Text>
          <TextInput
            style={styles.talepInput}
            value={talep}
            onChangeText={setTalep}
            placeholder={
              'Örnek: Müvekkilim 5 yıldır çalıştığı şirketten haksız işten çıkarıldı. ' +
              'Kıdem ve ihbar tazminatı ödenmedi...'
            }
            placeholderTextColor={Colors.textTertiary}
            multiline
            numberOfLines={5}
            textAlignVertical="top"
          />
          <Text style={styles.charCount}>{talep.length} karakter</Text>
        </View>

        {/* Ek seçenekler */}
        <TouchableOpacity
          style={styles.optionsToggle}
          onPress={() => setCategoryHint(prev => prev === '_open' ? '' : '_open')}
        >
          <Text style={styles.optionsToggleText}>Gelişmiş seçenekler ›</Text>
        </TouchableOpacity>

        {categoryHint === '_open' && (
          <View style={styles.section}>
            <Text style={styles.label}>KATEGORİ FİLTRESİ (isteğe bağlı)</Text>
            <TextInput
              style={styles.smallInput}
              value={categoryHint === '_open' ? '' : categoryHint}
              onChangeText={v => setCategoryHint(v || '_open')}
              placeholder="örn: İş Hukuku, Vergi Hukuku"
              placeholderTextColor={Colors.textTertiary}
            />
            <Text style={styles.label} style={{ marginTop: Spacing.md }}>EK NOT</Text>
            <TextInput
              style={[styles.smallInput, { height: 70 }]}
              value={extraContext}
              onChangeText={setExtraContext}
              placeholder="Mahkeme adı, taraf isimleri, özel notlar..."
              placeholderTextColor={Colors.textTertiary}
              multiline
              textAlignVertical="top"
            />
            <TouchableOpacity
              style={styles.haikuRow}
              onPress={() => setUseHaiku(v => !v)}
            >
              <View style={[styles.checkbox, useHaiku && styles.checkboxChecked]}>
                {useHaiku && <Text style={styles.checkmark}>✓</Text>}
              </View>
              <Text style={styles.haikuLabel}>Hızlı mod (Haiku — daha ucuz, biraz daha kısa)</Text>
            </TouchableOpacity>
          </View>
        )}

        {/* Üret butonu */}
        <TouchableOpacity
          style={[styles.generateBtn, { backgroundColor: typeInfo.color }, generating && styles.generateBtnDisabled]}
          onPress={handleGenerate}
          disabled={generating}
          activeOpacity={0.85}
        >
          {generating
            ? <ActivityIndicator color={Colors.white} />
            : <Text style={styles.generateBtnText}>Dilekçeyi Oluştur</Text>
          }
        </TouchableOpacity>

        {/* Uyarı */}
        {warning !== '' && (
          <View style={styles.warningBox}>
            <Text style={styles.warningText}>⚠ {warning}</Text>
          </View>
        )}

        {/* Kullanılan kararnameler */}
        {usedDecrees.length > 0 && (
          <View style={styles.decreesBox}>
            <Text style={styles.decreesTitle}>Kullanılan kararnameler</Text>
            {usedDecrees.map((d, i) => (
              <View key={i} style={styles.decreesItem}>
                <View style={[styles.simBar, { width: `${Math.round(d.similarity * 100)}%` }]} />
                <Text style={styles.decreesText} numberOfLines={2}>{d.title}</Text>
                <Text style={styles.decreesDate}>{d.gazette_date} · {d.madde_no}</Text>
              </View>
            ))}
          </View>
        )}

        {/* Üretilen metin önizleme */}
        {generatedText !== '' && (
          <View style={styles.previewBox}>
            <View style={styles.previewHeader}>
              <Text style={styles.previewTitle}>Dilekçe Önizleme</Text>
              {costInfo !== '' && (
                <Text style={styles.costBadge}>Maliyet: {costInfo}</Text>
              )}
            </View>
            <Text style={styles.previewText} selectable>
              {generatedText}
            </Text>
            {petitionId !== null && (
              <TouchableOpacity
                style={[styles.viewBtn, { borderColor: typeInfo.color }]}
                onPress={handleViewPetition}
              >
                <Text style={[styles.viewBtnText, { color: typeInfo.color }]}>
                  Tam Görünüm ve PDF İndir →
                </Text>
              </TouchableOpacity>
            )}
          </View>
        )}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex:    { flex: 1, backgroundColor: Colors.background },
  screen:  { flex: 1 },
  content: { padding: Spacing.lg, paddingBottom: Spacing.xxl },

  typeHeader: {
    flexDirection:  'row',
    alignItems:     'center',
    gap:            Spacing.md,
    borderRadius:   Radius.lg,
    padding:        Spacing.md,
    marginBottom:   Spacing.lg,
  },
  typeEmoji: { fontSize: 32 },
  typeName:  { fontSize: 16, fontWeight: '700' },
  typeDesc:  { ...Typography.small, marginTop: 2 },

  modeToggle: {
    flexDirection:   'row',
    backgroundColor: Colors.surface,
    borderRadius:    Radius.md,
    padding:         4,
    marginBottom:    Spacing.lg,
    ...Shadow.sm,
  },
  modeBtn: {
    flex:           1,
    paddingVertical: 10,
    alignItems:     'center',
    borderRadius:   Radius.sm,
  },
  modeBtnActive: { backgroundColor: Colors.primary },
  modeBtnText:     { fontSize: 14, color: Colors.textSecondary, fontWeight: '500' },
  modeBtnTextActive: { color: Colors.white },

  voiceSection: { alignItems: 'center', marginBottom: Spacing.lg },
  micWrap:      {},
  micBtn: {
    width:           88,
    height:          88,
    borderRadius:    44,
    backgroundColor: Colors.primaryLight,
    alignItems:      'center',
    justifyContent:  'center',
    borderWidth:     2,
    borderColor:     Colors.primary,
    ...Shadow.md,
  },
  micBtnActive: { backgroundColor: Colors.danger, borderColor: Colors.danger },
  micIcon:      { fontSize: 36 },
  micHint:      { ...Typography.small, marginTop: Spacing.md, textAlign: 'center' },

  section:      { marginBottom: Spacing.md },
  label:        { ...Typography.label, marginBottom: Spacing.xs },
  talepInput: {
    backgroundColor:   Colors.surface,
    borderWidth:       1,
    borderColor:       Colors.border,
    borderRadius:      Radius.md,
    padding:           Spacing.md,
    fontSize:          15,
    color:             Colors.textPrimary,
    minHeight:         120,
    lineHeight:        22,
  },
  charCount: { ...Typography.small, fontSize: 11, textAlign: 'right', marginTop: 4 },
  smallInput: {
    backgroundColor: Colors.surface,
    borderWidth:     1,
    borderColor:     Colors.border,
    borderRadius:    Radius.md,
    paddingHorizontal: Spacing.md,
    paddingVertical: 10,
    fontSize:        14,
    color:           Colors.textPrimary,
    marginBottom:    Spacing.sm,
  },

  optionsToggle:     { marginBottom: Spacing.sm },
  optionsToggleText: { ...Typography.small, color: Colors.primary, fontWeight: '600' },

  haikuRow:         { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm, marginTop: Spacing.sm },
  checkbox:         { width: 20, height: 20, borderWidth: 1.5, borderColor: Colors.border, borderRadius: 4, alignItems: 'center', justifyContent: 'center' },
  checkboxChecked:  { backgroundColor: Colors.primary, borderColor: Colors.primary },
  checkmark:        { color: Colors.white, fontSize: 12, fontWeight: '700' },
  haikuLabel:       { ...Typography.small, flex: 1 },

  generateBtn: {
    borderRadius:    Radius.md,
    paddingVertical: 16,
    alignItems:      'center',
    marginVertical:  Spacing.md,
    ...Shadow.md,
  },
  generateBtnDisabled: { opacity: 0.7 },
  generateBtnText:     { color: Colors.white, fontSize: 16, fontWeight: '700' },

  warningBox: {
    backgroundColor: Colors.warningLight,
    borderRadius:    Radius.md,
    padding:         Spacing.md,
    marginBottom:    Spacing.md,
    borderLeftWidth: 3,
    borderLeftColor: Colors.warning,
  },
  warningText: { ...Typography.small, color: Colors.warning },

  decreesBox: {
    backgroundColor: Colors.surface,
    borderRadius:    Radius.lg,
    padding:         Spacing.md,
    marginBottom:    Spacing.md,
    ...Shadow.sm,
  },
  decreesTitle: { ...Typography.label, marginBottom: Spacing.sm },
  decreesItem:  { marginBottom: Spacing.sm },
  simBar: {
    height: 3, backgroundColor: Colors.primaryLight,
    borderRadius: 2, marginBottom: 4, maxWidth: '100%',
  },
  decreesText: { fontSize: 13, color: Colors.textPrimary, fontWeight: '500' },
  decreesDate: { fontSize: 11, color: Colors.textTertiary, marginTop: 1 },

  previewBox: {
    backgroundColor: Colors.surface,
    borderRadius:    Radius.lg,
    padding:         Spacing.md,
    ...Shadow.md,
  },
  previewHeader: {
    flexDirection:  'row',
    justifyContent: 'space-between',
    alignItems:     'center',
    marginBottom:   Spacing.sm,
  },
  previewTitle: { ...Typography.h3, fontSize: 14 },
  costBadge: {
    fontSize:        11,
    color:           Colors.success,
    backgroundColor: Colors.successLight,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius:    Radius.full,
    fontWeight:      '600',
  },
  previewText: {
    ...Typography.body,
    fontSize:   13,
    lineHeight: 21,
    color:      Colors.textSecondary,
    maxHeight:  300,
  },
  viewBtn: {
    marginTop:     Spacing.md,
    borderWidth:   1.5,
    borderRadius:  Radius.md,
    paddingVertical: 12,
    alignItems:    'center',
  },
  viewBtnText: { fontSize: 14, fontWeight: '600' },
});
