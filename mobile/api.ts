// services/api.ts — Backend API istemcisi

import AsyncStorage from '@react-native-async-storage/async-storage';

const BASE_URL = process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000';

// ── Token yönetimi ────────────────────────────────────────────────────────────

export const TokenStore = {
  async get(): Promise<string | null> {
    return AsyncStorage.getItem('access_token');
  },
  async set(token: string) {
    await AsyncStorage.setItem('access_token', token);
  },
  async clear() {
    await AsyncStorage.multiRemove(['access_token', 'lawyer_info']);
  },
};

// ── Temel fetch sarmalayıcı ───────────────────────────────────────────────────

async function apiFetch(
  path: string,
  options: RequestInit = {},
  auth = true,
): Promise<Response> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };

  if (auth) {
    const token = await TokenStore.get();
    if (token) headers['Authorization'] = `Bearer ${token}`;
  }

  const res = await fetch(`${BASE_URL}${path}`, { ...options, headers });

  if (res.status === 401) {
    await TokenStore.clear();
    throw new ApiError(401, 'Oturum süresi doldu. Lütfen tekrar giriş yapın.');
  }

  return res;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function parseResponse<T>(res: Response): Promise<T> {
  const data = await res.json();
  if (!res.ok) {
    throw new ApiError(res.status, data.detail ?? 'Bir hata oluştu');
  }
  return data as T;
}

// ── Auth API ──────────────────────────────────────────────────────────────────

export interface LoginResponse {
  access_token: string;
  lawyer_id:    number;
  full_name:    string;
  expires_in:   number;
}

export interface RegisterPayload {
  full_name:  string;
  email:      string;
  password:   string;
  bar_number: string;
  baro:       string;
  firm_name?: string;
}

export const AuthAPI = {
  async login(email: string, password: string): Promise<LoginResponse> {
    const res = await apiFetch('/auth/login', {
      method: 'POST',
      body:   JSON.stringify({ email, password }),
    }, false);
    return parseResponse<LoginResponse>(res);
  },

  async register(payload: RegisterPayload): Promise<LoginResponse> {
    const res = await apiFetch('/auth/register', {
      method: 'POST',
      body:   JSON.stringify(payload),
    }, false);
    return parseResponse<LoginResponse>(res);
  },
};

// ── Dilekçe API ───────────────────────────────────────────────────────────────

export interface PetitionHistoryItem {
  id:            number;
  petition_type: string;
  subject:       string;
  status:        string;
  created_at:    string;
}

export interface PetitionDetail {
  id:             number;
  petition_type:  string;
  subject:        string;
  generated_text: string;
  used_decree_ids: number[];
  status:         string;
  created_at:     string;
}

export interface GeneratePayload {
  petition_type:  string;
  talep:          string;
  category_hint?: string;
  use_haiku?:     boolean;
  extra_context?: string;
}

export const PetitionAPI = {
  async getHistory(limit = 20): Promise<PetitionHistoryItem[]> {
    const res = await apiFetch(`/petition/history?limit=${limit}`);
    return parseResponse<PetitionHistoryItem[]>(res);
  },

  async getDetail(id: number): Promise<PetitionDetail> {
    const res = await apiFetch(`/petition/${id}`);
    return parseResponse<PetitionDetail>(res);
  },

  async revise(petitionId: number, revisionNote: string): Promise<{ revised_text: string }> {
    const res = await apiFetch('/petition/revise', {
      method: 'POST',
      body:   JSON.stringify({ petition_id: petitionId, revision_note: revisionNote }),
    });
    return parseResponse(res);
  },

  // Streaming üretim — callback ile her chunk'ı iletir
  async generateStream(
    payload: GeneratePayload,
    onChunk:   (text: string) => void,
    onMeta:    (meta: { used_decrees: any[]; model: string }) => void,
    onWarning: (msg: string) => void,
    onDone:    (meta: { petition_id: number; cost_usd: number }) => void,
    onError:   (err: string) => void,
  ): Promise<void> {
    const token = await TokenStore.get();
    const res   = await fetch(`${BASE_URL}/petition/stream`, {
      method:  'POST',
      headers: {
        'Content-Type':  'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      onError('Dilekçe üretilemedi. Lütfen tekrar deneyin.');
      return;
    }

    const reader  = res.body!.getReader();
    const decoder = new TextDecoder();
    let   buffer  = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const event = JSON.parse(line.slice(6));
          if      (event.type === 'chunk'   ) onChunk(event.data);
          else if (event.type === 'meta'    ) onMeta(event.data);
          else if (event.type === 'warning' ) onWarning(event.data);
          else if (event.type === 'done'    ) onDone(event.data);
          else if (event.type === 'error'   ) onError(event.data);
        } catch { /* JSON parse hatası — atla */ }
      }
    }
  },

  // Ses transkripsiyonu
  async transcribeAudio(uri: string, mimeType = 'audio/m4a'): Promise<string> {
    const token    = await TokenStore.get();
    const formData = new FormData();
    formData.append('audio', { uri, type: mimeType, name: 'kayit.m4a' } as any);

    const res = await fetch(`${BASE_URL}/petition/transcribe`, {
      method:  'POST',
      headers: { 'Authorization': `Bearer ${token}` },
      body:    formData,
    });
    const data = await res.json();
    if (!res.ok) throw new ApiError(res.status, data.detail);
    return data.transcription as string;
  },
};
