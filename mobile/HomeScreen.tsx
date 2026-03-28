// screens/HomeScreen.tsx — Ana ekran

import React, { useEffect, useState, useCallback } from 'react';
import {
  View, Text, ScrollView, TouchableOpacity,
  StyleSheet, RefreshControl, ActivityIndicator,
} from 'react-native';
import { useNavigation, useFocusEffect } from '@react-navigation/native';
import { Colors, Typography, Spacing, Radius, Shadow, PETITION_TYPES } from '../theme';
import { useAuth } from '../hooks/useAuth';
import { PetitionAPI, PetitionHistoryItem } from '../services/api';

const TYPE_BG: Record<string, string> = {
  mahkeme:   '#E8EDF7',
  ihtarname: '#F3ECF8',
  idari:     '#E8F5EE',
  icra:      '#FDF3E3',
};

function PetitionTypeCard({
  type, onPress,
}: {
  type: typeof PETITION_TYPES[0];
  onPress: () => void;
}) {
  return (
    <TouchableOpacity style={styles.typeCard} onPress={onPress} activeOpacity={0.8}>
      <View style={[styles.typeIconWrap, { backgroundColor: TYPE_BG[type.key] }]}>
        <Text style={styles.typeIcon}>{type.icon}</Text>
      </View>
      <Text style={styles.typeLabel}>{type.label}</Text>
      <Text style={styles.typeDesc}>{type.description}</Text>
    </TouchableOpacity>
  );
}

function HistoryCard({ item, onPress }: { item: PetitionHistoryItem; onPress: () => void }) {
  const typeInfo = PETITION_TYPES.find(t => t.key === item.petition_type);
  const date     = new Date(item.created_at).toLocaleDateString('tr-TR', {
    day: 'numeric', month: 'long', year: 'numeric',
  });
  const statusColor = item.status === 'draft' ? Colors.warning : Colors.success;
  const statusLabel = item.status === 'draft' ? 'Taslak' : 'Tamamlandı';

  return (
    <TouchableOpacity style={styles.historyCard} onPress={onPress} activeOpacity={0.8}>
      <View style={styles.historyLeft}>
        <View style={[styles.historyDot, { backgroundColor: typeInfo?.color ?? Colors.primary }]} />
        <View style={styles.historyInfo}>
          <Text style={styles.historyType}>{typeInfo?.label ?? item.petition_type}</Text>
          <Text style={styles.historySubject} numberOfLines={2}>{item.subject}</Text>
          <Text style={styles.historyDate}>{date}</Text>
        </View>
      </View>
      <View style={[styles.statusBadge, { backgroundColor: statusColor + '20' }]}>
        <Text style={[styles.statusText, { color: statusColor }]}>{statusLabel}</Text>
      </View>
    </TouchableOpacity>
  );
}

export default function HomeScreen() {
  const navigation  = useNavigation<any>();
  const { lawyer, logout } = useAuth();

  const [history,    setHistory]    = useState<PetitionHistoryItem[]>([]);
  const [loading,    setLoading]    = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const loadHistory = useCallback(async () => {
    try {
      const data = await PetitionAPI.getHistory(10);
      setHistory(data);
    } catch { /* sessiz hata */ }
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useFocusEffect(useCallback(() => { loadHistory(); }, [loadHistory]));

  const hour     = new Date().getHours();
  const greeting = hour < 12 ? 'Günaydın' : hour < 18 ? 'İyi günler' : 'İyi akşamlar';

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); loadHistory(); }} />}
    >
      {/* Header */}
      <View style={styles.header}>
        <View>
          <Text style={styles.greeting}>{greeting},</Text>
          <Text style={styles.lawyerName}>Av. {lawyer?.name}</Text>
        </View>
        <TouchableOpacity style={styles.logoutBtn} onPress={logout}>
          <Text style={styles.logoutIcon}>↩</Text>
        </TouchableOpacity>
      </View>

      {/* Hızlı istatistik */}
      <View style={styles.statsRow}>
        <View style={styles.statCard}>
          <Text style={styles.statNum}>{history.length}</Text>
          <Text style={styles.statLabel}>Bu ay dilekçe</Text>
        </View>
        <View style={styles.statCard}>
          <Text style={styles.statNum}>
            {history.filter(h => h.status === 'draft').length}
          </Text>
          <Text style={styles.statLabel}>Taslak</Text>
        </View>
        <View style={styles.statCard}>
          <Text style={styles.statNum}>4</Text>
          <Text style={styles.statLabel}>Dilekçe türü</Text>
        </View>
      </View>

      {/* Yeni dilekçe */}
      <Text style={styles.sectionTitle}>Yeni Dilekçe</Text>
      <View style={styles.typeGrid}>
        {PETITION_TYPES.map(type => (
          <PetitionTypeCard
            key={type.key}
            type={type}
            onPress={() => navigation.navigate('NewPetition', { petitionType: type.key })}
          />
        ))}
      </View>

      {/* Geçmiş */}
      <Text style={styles.sectionTitle}>Son Dilekçeler</Text>
      {loading ? (
        <ActivityIndicator color={Colors.primary} style={{ marginTop: Spacing.lg }} />
      ) : history.length === 0 ? (
        <View style={styles.emptyBox}>
          <Text style={styles.emptyIcon}>📄</Text>
          <Text style={styles.emptyText}>Henüz dilekçe oluşturmadınız.</Text>
          <Text style={styles.emptyHint}>Yukarıdan bir tür seçerek başlayın.</Text>
        </View>
      ) : (
        history.map(item => (
          <HistoryCard
            key={item.id}
            item={item}
            onPress={() => navigation.navigate('PetitionDetail', { petitionId: item.id })}
          />
        ))
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen:  { flex: 1, backgroundColor: Colors.background },
  content: { padding: Spacing.lg, paddingBottom: Spacing.xxl },

  header: {
    flexDirection:  'row',
    justifyContent: 'space-between',
    alignItems:     'flex-start',
    marginBottom:   Spacing.lg,
  },
  greeting:   { ...Typography.small, color: Colors.textSecondary },
  lawyerName: { ...Typography.h2, marginTop: 2 },
  logoutBtn: {
    padding:         8,
    backgroundColor: Colors.surface,
    borderRadius:    Radius.full,
    ...Shadow.sm,
  },
  logoutIcon: { fontSize: 18, color: Colors.textSecondary },

  statsRow: {
    flexDirection:  'row',
    gap:            Spacing.sm,
    marginBottom:   Spacing.lg,
  },
  statCard: {
    flex:            1,
    backgroundColor: Colors.primary,
    borderRadius:    Radius.md,
    padding:         Spacing.md,
    alignItems:      'center',
  },
  statNum:   { fontSize: 22, fontWeight: '700', color: Colors.white },
  statLabel: { fontSize: 11, color: 'rgba(255,255,255,0.75)', marginTop: 2 },

  sectionTitle: {
    ...Typography.h3,
    marginBottom: Spacing.md,
    marginTop:    Spacing.sm,
  },

  typeGrid: {
    flexDirection:  'row',
    flexWrap:       'wrap',
    gap:            Spacing.sm,
    marginBottom:   Spacing.lg,
  },
  typeCard: {
    width:           '47.5%',
    backgroundColor: Colors.surface,
    borderRadius:    Radius.lg,
    padding:         Spacing.md,
    ...Shadow.sm,
  },
  typeIconWrap: {
    width:         44,
    height:        44,
    borderRadius:  Radius.md,
    alignItems:    'center',
    justifyContent:'center',
    marginBottom:  Spacing.sm,
  },
  typeIcon:  { fontSize: 22 },
  typeLabel: { ...Typography.body, fontWeight: '600', fontSize: 13, marginBottom: 2 },
  typeDesc:  { ...Typography.small, fontSize: 11, color: Colors.textTertiary },

  historyCard: {
    backgroundColor: Colors.surface,
    borderRadius:    Radius.lg,
    padding:         Spacing.md,
    flexDirection:   'row',
    alignItems:      'center',
    justifyContent:  'space-between',
    marginBottom:    Spacing.sm,
    ...Shadow.sm,
  },
  historyLeft:    { flex: 1, flexDirection: 'row', alignItems: 'flex-start', gap: Spacing.sm },
  historyDot:     { width: 4, height: '100%', borderRadius: 2, minHeight: 40 },
  historyInfo:    { flex: 1 },
  historyType:    { fontSize: 11, fontWeight: '600', color: Colors.textSecondary, marginBottom: 2 },
  historySubject: { ...Typography.body, fontSize: 14, fontWeight: '500', marginBottom: 3 },
  historyDate:    { ...Typography.small, fontSize: 11, color: Colors.textTertiary },
  statusBadge:    { paddingHorizontal: 8, paddingVertical: 4, borderRadius: Radius.full },
  statusText:     { fontSize: 11, fontWeight: '600' },

  emptyBox: {
    alignItems:      'center',
    backgroundColor: Colors.surface,
    borderRadius:    Radius.lg,
    padding:         Spacing.xl,
    ...Shadow.sm,
  },
  emptyIcon: { fontSize: 36, marginBottom: Spacing.sm },
  emptyText: { ...Typography.body, fontWeight: '500', marginBottom: 4 },
  emptyHint: { ...Typography.small, textAlign: 'center' },
});
