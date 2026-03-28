// screens/PetitionDetailScreen.tsx — Dilekçe detay, PDF ve revizyon

import React, { useEffect, useState, useCallback } from 'react';
import {
  View, Text, ScrollView, TouchableOpacity, StyleSheet,
  Share, Alert, Modal, TextInput, ActivityIndicator,
} from 'react-native';
import { useRoute } from '@react-navigation/native';
import * as Print from 'expo-print';
import * as Sharing from 'expo-sharing';
import { Colors, Typography, Spacing, Radius, Shadow, PETITION_TYPES } from '../theme';
import { PetitionAPI, PetitionDetail } from '../services/api';

function buildHtml(petition: PetitionDetail): string {
  const typeInfo = PETITION_TYPES.find(t => t.key === petition.petition_type);
  const date     = new Date(petition.created_at).toLocaleDateString('tr-TR', {
    day: 'numeric', month: 'long', year: 'numeric',
  });

  // Metni paragraflara böl, her satırı HTML'e çevir
  const bodyHtml = petition.generated_text
    .split('\n')
    .map(line => {
      const trimmed = line.trim();
      if (!trimmed) return '<br>';
      if (trimmed === trimmed.toUpperCase() && trimmed.length > 3) {
        return `<p class="heading">${trimmed}</p>`;
      }
      return `<p>${trimmed}</p>`;
    })
    .join('\n');

  return `<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="UTF-8">
  <style>
    @page { margin: 2.5cm 2cm; }
    body {
      font-family: 'Times New Roman', Times, serif;
      font-size: 12pt;
      line-height: 1.8;
      color: #1a1a1a;
    }
    .meta {
      font-size: 10pt;
      color: #555;
      border-bottom: 1px solid #ddd;
      padding-bottom: 8pt;
      margin-bottom: 16pt;
    }
    p { margin: 0 0 6pt 0; text-align: justify; }
    p.heading {
      font-weight: bold;
      margin: 14pt 0 6pt;
      text-align: center;
    }
    br { display: block; margin: 4pt 0; }
  </style>
</head>
<body>
  <div class="meta">
    Hukuk AI — ${typeInfo?.label ?? petition.petition_type} | ${date}
  </div>
  ${bodyHtml}
</body>
</html>`;
}

export default function PetitionDetailScreen() {
  const route = useRoute<any>();
  const petitionId: number = route.params?.petitionId;

  const [petition,    setPetition]    = useState<PetitionDetail | null>(null);
  const [loading,     setLoading]     = useState(true);
  const [exporting,   setExporting]   = useState(false);
  const [reviseModal, setReviseModal] = useState(false);
  const [reviseNote,  setReviseNote]  = useState('');
  const [revising,    setRevising]    = useState(false);

  const loadPetition = useCallback(async () => {
    try {
      const data = await PetitionAPI.getDetail(petitionId);
      setPetition(data);
    } catch (e: any) {
      Alert.alert('Hata', e.message);
    } finally {
      setLoading(false);
    }
  }, [petitionId]);

  useEffect(() => { loadPetition(); }, [loadPetition]);

  // ── PDF export ─────────────────────────────────────────────────────────────

  const handleExportPDF = async () => {
    if (!petition) return;
    setExporting(true);
    try {
      const html = buildHtml(petition);
      const { uri } = await Print.printToFileAsync({ html, base64: false });
      if (await Sharing.isAvailableAsync()) {
        await Sharing.shareAsync(uri, {
          mimeType: 'application/pdf',
          dialogTitle: 'Dilekçeyi Paylaş',
          UTI: 'com.adobe.pdf',
        });
      } else {
        Alert.alert('PDF hazır', `Dosya kaydedildi:\n${uri}`);
      }
    } catch (e: any) {
      Alert.alert('PDF hatası', e.message);
    } finally {
      setExporting(false);
    }
  };

  // ── Metin paylaş ──────────────────────────────────────────────────────────

  const handleShare = async () => {
    if (!petition) return;
    await Share.share({
      message: petition.generated_text,
      title:   `Dilekçe — ${petition.subject}`,
    });
  };

  // ── Revizyon ──────────────────────────────────────────────────────────────

  const handleRevise = async () => {
    if (!petition || reviseNote.trim().length < 5) return;
    setRevising(true);
    try {
      const res = await PetitionAPI.revise(petition.id, reviseNote.trim());
      setPetition(prev => prev ? { ...prev, generated_text: res.revised_text } : prev);
      setReviseModal(false);
      setReviseNote('');
      Alert.alert('Revize edildi', 'Dilekçe güncellendi.');
    } catch (e: any) {
      Alert.alert('Revizyon hatası', e.message);
    } finally {
      setRevising(false);
    }
  };

  // ── Render ────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color={Colors.primary} />
        <Text style={styles.loadingText}>Dilekçe yükleniyor...</Text>
      </View>
    );
  }

  if (!petition) {
    return (
      <View style={styles.center}>
        <Text style={styles.errorText}>Dilekçe bulunamadı.</Text>
      </View>
    );
  }

  const typeInfo = PETITION_TYPES.find(t => t.key === petition.petition_type);
  const date     = new Date(petition.created_at).toLocaleDateString('tr-TR', {
    day: 'numeric', month: 'long', year: 'numeric',
  });

  return (
    <>
      <ScrollView style={styles.screen} contentContainerStyle={styles.content}>

        {/* Başlık kartı */}
        <View style={styles.headerCard}>
          <View style={styles.headerTop}>
            <View style={[styles.typePill, { backgroundColor: (typeInfo?.color ?? Colors.primary) + '20' }]}>
              <Text style={styles.typePillIcon}>{typeInfo?.icon}</Text>
              <Text style={[styles.typePillText, { color: typeInfo?.color ?? Colors.primary }]}>
                {typeInfo?.label}
              </Text>
            </View>
            <Text style={styles.dateText}>{date}</Text>
          </View>
          <Text style={styles.subjectText} numberOfLines={3}>{petition.subject}</Text>
        </View>

        {/* Eylem butonları */}
        <View style={styles.actionsRow}>
          <TouchableOpacity
            style={[styles.actionBtn, styles.actionPrimary]}
            onPress={handleExportPDF}
            disabled={exporting}
          >
            {exporting
              ? <ActivityIndicator color={Colors.white} size="small" />
              : <Text style={styles.actionBtnTextPrimary}>PDF İndir</Text>
            }
          </TouchableOpacity>

          <TouchableOpacity style={styles.actionBtn} onPress={handleShare}>
            <Text style={styles.actionBtnText}>Paylaş</Text>
          </TouchableOpacity>

          <TouchableOpacity
            style={styles.actionBtn}
            onPress={() => setReviseModal(true)}
          >
            <Text style={styles.actionBtnText}>Revize Et</Text>
          </TouchableOpacity>
        </View>

        {/* Dilekçe metni */}
        <View style={styles.textCard}>
          <Text style={styles.textContent} selectable>
            {petition.generated_text}
          </Text>
        </View>

      </ScrollView>

      {/* Revizyon modal */}
      <Modal
        visible={reviseModal}
        animationType="slide"
        transparent
        onRequestClose={() => setReviseModal(false)}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Revizyon Notu</Text>
            <Text style={styles.modalHint}>
              Dilekçede neyi değiştirmek istediğinizi yazın.
            </Text>
            <TextInput
              style={styles.modalInput}
              value={reviseNote}
              onChangeText={setReviseNote}
              placeholder="örn: Davacı adını Ahmet Yılmaz olarak güncelle, talep miktarını 50.000 TL yap..."
              placeholderTextColor={Colors.textTertiary}
              multiline
              numberOfLines={4}
              textAlignVertical="top"
              autoFocus
            />
            <View style={styles.modalActions}>
              <TouchableOpacity
                style={styles.modalCancelBtn}
                onPress={() => setReviseModal(false)}
              >
                <Text style={styles.modalCancelText}>İptal</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.modalConfirmBtn, revising && { opacity: 0.7 }]}
                onPress={handleRevise}
                disabled={revising}
              >
                {revising
                  ? <ActivityIndicator color={Colors.white} size="small" />
                  : <Text style={styles.modalConfirmText}>Revize Et</Text>
                }
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  screen:  { flex: 1, backgroundColor: Colors.background },
  content: { padding: Spacing.lg, paddingBottom: Spacing.xxl },
  center:  { flex: 1, alignItems: 'center', justifyContent: 'center', gap: Spacing.md },
  loadingText: { ...Typography.small },
  errorText:   { ...Typography.body, color: Colors.danger },

  headerCard: {
    backgroundColor: Colors.surface,
    borderRadius:    Radius.lg,
    padding:         Spacing.lg,
    marginBottom:    Spacing.md,
    ...Shadow.sm,
  },
  headerTop: {
    flexDirection:  'row',
    justifyContent: 'space-between',
    alignItems:     'center',
    marginBottom:   Spacing.sm,
  },
  typePill: {
    flexDirection:  'row',
    alignItems:     'center',
    gap:            6,
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius:   Radius.full,
  },
  typePillIcon: { fontSize: 14 },
  typePillText: { fontSize: 12, fontWeight: '600' },
  dateText:     { ...Typography.small, fontSize: 11 },
  subjectText:  { ...Typography.body, fontWeight: '500', lineHeight: 22 },

  actionsRow: {
    flexDirection:  'row',
    gap:            Spacing.sm,
    marginBottom:   Spacing.md,
  },
  actionBtn: {
    flex:            1,
    backgroundColor: Colors.surface,
    borderRadius:    Radius.md,
    paddingVertical: 11,
    alignItems:      'center',
    borderWidth:     1,
    borderColor:     Colors.border,
  },
  actionPrimary:        { backgroundColor: Colors.primary, borderColor: Colors.primary },
  actionBtnText:        { fontSize: 13, fontWeight: '600', color: Colors.textSecondary },
  actionBtnTextPrimary: { fontSize: 13, fontWeight: '600', color: Colors.white },

  textCard: {
    backgroundColor: Colors.surface,
    borderRadius:    Radius.lg,
    padding:         Spacing.lg,
    ...Shadow.sm,
  },
  textContent: {
    fontFamily: Platform.OS === 'ios' ? 'Georgia' : 'serif',
    fontSize:   14,
    lineHeight: 24,
    color:      Colors.textPrimary,
  } as any,

  // Modal
  modalOverlay: {
    flex:            1,
    backgroundColor: 'rgba(0,0,0,0.5)',
    justifyContent:  'flex-end',
  },
  modalCard: {
    backgroundColor: Colors.surface,
    borderTopLeftRadius:  Radius.xl,
    borderTopRightRadius: Radius.xl,
    padding:              Spacing.lg,
    paddingBottom:        Spacing.xxl,
  },
  modalTitle: { ...Typography.h3, marginBottom: Spacing.xs },
  modalHint:  { ...Typography.small, marginBottom: Spacing.md },
  modalInput: {
    backgroundColor:   Colors.background,
    borderRadius:      Radius.md,
    borderWidth:       1,
    borderColor:       Colors.border,
    padding:           Spacing.md,
    fontSize:          14,
    color:             Colors.textPrimary,
    minHeight:         100,
    lineHeight:        21,
    marginBottom:      Spacing.md,
  },
  modalActions:      { flexDirection: 'row', gap: Spacing.sm },
  modalCancelBtn: {
    flex:            1,
    borderWidth:     1,
    borderColor:     Colors.border,
    borderRadius:    Radius.md,
    paddingVertical: 13,
    alignItems:      'center',
  },
  modalCancelText:   { fontSize: 14, fontWeight: '600', color: Colors.textSecondary },
  modalConfirmBtn: {
    flex:            2,
    backgroundColor: Colors.primary,
    borderRadius:    Radius.md,
    paddingVertical: 13,
    alignItems:      'center',
  },
  modalConfirmText: { fontSize: 14, fontWeight: '600', color: Colors.white },
});

const { Platform } = require('react-native');
