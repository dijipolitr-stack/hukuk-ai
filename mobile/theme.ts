// theme.ts — Uygulama geneli renk ve stil sabitleri

export const Colors = {
  // Ana renkler
  primary:        '#2D4A8A',   // Koyu mavi — hukuk/güven
  primaryLight:   '#E8EDF7',
  primaryDark:    '#1A2E5A',

  // Vurgu
  accent:         '#C8A45A',   // Altın — prestij

  // Durum renkleri
  success:        '#1D7A4F',
  successLight:   '#E8F5EE',
  warning:        '#B87333',
  warningLight:   '#FDF3E3',
  danger:         '#C0392B',
  dangerLight:    '#FDECEA',

  // Nötr
  white:          '#FFFFFF',
  background:     '#F4F6FB',
  surface:        '#FFFFFF',
  border:         '#DDE2EE',
  borderLight:    '#EEF1F8',

  // Metin
  textPrimary:    '#1A2238',
  textSecondary:  '#5A6482',
  textTertiary:   '#9BA3BE',
  textOnPrimary:  '#FFFFFF',

  // Dilekçe türü renkleri
  mahkeme:        '#2D4A8A',
  ihtarname:      '#7B3FA0',
  idari:          '#1D7A4F',
  icra:           '#B87333',
};

export const Typography = {
  h1:    { fontSize: 26, fontWeight: '700' as const, color: Colors.textPrimary },
  h2:    { fontSize: 20, fontWeight: '700' as const, color: Colors.textPrimary },
  h3:    { fontSize: 17, fontWeight: '600' as const, color: Colors.textPrimary },
  body:  { fontSize: 15, fontWeight: '400' as const, color: Colors.textPrimary, lineHeight: 23 },
  small: { fontSize: 13, fontWeight: '400' as const, color: Colors.textSecondary },
  label: { fontSize: 12, fontWeight: '600' as const, color: Colors.textSecondary, letterSpacing: 0.5 },
};

export const Spacing = {
  xs: 4, sm: 8, md: 16, lg: 24, xl: 32, xxl: 48,
};

export const Radius = {
  sm: 6, md: 10, lg: 16, xl: 24, full: 999,
};

export const Shadow = {
  sm: {
    shadowColor: '#1A2238',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.08,
    shadowRadius: 4,
    elevation: 2,
  },
  md: {
    shadowColor: '#1A2238',
    shadowOffset: { width: 0, height: 3 },
    shadowOpacity: 0.12,
    shadowRadius: 8,
    elevation: 4,
  },
};

// Dilekçe türü meta bilgileri
export const PETITION_TYPES = [
  {
    key:         'mahkeme',
    label:       'Mahkemeye Dilekçe',
    description: 'Dava, itiraz, cevap dilekçeleri',
    color:       Colors.mahkeme,
    icon:        '⚖️',
  },
  {
    key:         'ihtarname',
    label:       'İhtarname',
    description: 'Noterden karşı tarafa ihtar',
    color:       Colors.ihtarname,
    icon:        '📋',
  },
  {
    key:         'idari',
    label:       'İdari Başvuru',
    description: 'Kamu kurumlarına başvuru',
    color:       Colors.idari,
    icon:        '🏛️',
  },
  {
    key:         'icra',
    label:       'İcra Takibi',
    description: 'Alacak ve haciz işlemleri',
    color:       Colors.icra,
    icon:        '📑',
  },
];
