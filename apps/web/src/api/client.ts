/**
 * API 客户端：负责与后端 FastAPI 或前端 Mock 引擎通信
 * 严格按照 docs/分工/00-总约定.md §5、§8 实现。
 * 真实模式下，失败绝不静默回退到 mock，必须真实抛出错误。
 */

import {
  ChatRequest,
  ChatResponse,
  Health,
  MemoryItem,
  MemoryKey,
  MemoryList,
  Message,
  OkResponse,
  SessionDTO,
} from './types';
import { mockEngine } from './mock';

export class ApiError extends Error {
  public status: number;
  public code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

export class ApiClient {
  private mockMode: boolean;
  private baseUrl: string;
  private sessionCookie: string | null = null;

  constructor(mockMode?: boolean, baseUrl: string = '') {
    if (typeof mockMode === 'boolean') {
      this.mockMode = mockMode;
    } else {
      // 环境变量判定：仅当显式设置 VITE_MOCK=1 时启用 mock
      const envMock = typeof import.meta !== 'undefined' && import.meta.env ? import.meta.env.VITE_MOCK : undefined;
      this.mockMode = envMock === '1' || envMock === 'true';
    }
    this.baseUrl = baseUrl;
  }

  public isMock(): boolean {
    return this.mockMode;
  }

  public setMock(enabled: boolean): void {
    this.mockMode = enabled;
  }

  public setBaseUrl(url: string): void {
    this.baseUrl = url;
  }

  public getSessionCookie(): string | null {
    return this.sessionCookie;
  }

  public setSessionCookie(cookie: string | null): void {
    this.sessionCookie = cookie;
  }

  private async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const headers: Record<string, string> = {
      Accept: 'application/json',
      ...((options.headers as Record<string, string>) || {}),
    };

    if (options.body && typeof options.body === 'string' && !headers['Content-Type']) {
      headers['Content-Type'] = 'application/json';
    }

    // Node 环境自动化测试支持 Cookie 透传
    if (this.sessionCookie && !headers['Cookie']) {
      headers['Cookie'] = this.sessionCookie;
    }

    const url = this.baseUrl ? `${this.baseUrl}${endpoint}` : endpoint;

    let res: Response;
    try {
      res = await fetch(url, {
        ...options,
        headers,
        credentials: 'include', // 必须带上 b2_anon cookie
      });
    } catch (networkErr: unknown) {
      throw new ApiError(
        0,
        'NETWORK_ERROR',
        `网络连接失败: ${networkErr instanceof Error ? networkErr.message : '无法连接后端服务器'}`
      );
    }

    // 在 Node 环境下记录服务端下发的 b2_anon Set-Cookie
    const setCookie = res.headers.get('set-cookie');
    if (setCookie) {
      const match = setCookie.match(/b2_anon=[^;]+/);
      if (match) {
        this.sessionCookie = match[0];
      }
    }

    let data: any = null;
    const text = await res.text();
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = text;
      }
    }

    if (!res.ok) {
      const code = data?.error?.code || `HTTP_${res.status}`;
      const message = data?.error?.message || (typeof data === 'string' ? data : `请求失败 (HTTP ${res.status})`);
      throw new ApiError(res.status, code, message);
    }

    return data as T;
  }

  public async getHealth(): Promise<Health> {
    if (this.mockMode) {
      return mockEngine.getHealth();
    }
    return this.request<Health>('/health', { method: 'GET' });
  }

  public async listSessions(): Promise<SessionDTO[]> {
    if (this.mockMode) {
      return mockEngine.listSessions();
    }
    return this.request<SessionDTO[]>('/api/sessions', { method: 'GET' });
  }

  public async createSession(title?: string): Promise<SessionDTO> {
    if (this.mockMode) {
      return mockEngine.createSession(title);
    }
    const body = title ? JSON.stringify({ title }) : JSON.stringify({ title: '新会话' });
    return this.request<SessionDTO>('/api/sessions', {
      method: 'POST',
      body,
    });
  }

  public async getSessionMessages(sessionId: string): Promise<Message[]> {
    if (this.mockMode) {
      return mockEngine.getSessionMessages(sessionId);
    }
    return this.request<Message[]>(`/api/sessions/${encodeURIComponent(sessionId)}/messages`, {
      method: 'GET',
    });
  }

  public async deleteSession(sessionId: string): Promise<OkResponse> {
    if (this.mockMode) {
      return mockEngine.deleteSession(sessionId);
    }
    return this.request<OkResponse>(`/api/sessions/${encodeURIComponent(sessionId)}`, {
      method: 'DELETE',
    });
  }

  public async sendChat(req: ChatRequest): Promise<ChatResponse> {
    if (this.mockMode) {
      return mockEngine.sendChat(req);
    }
    return this.request<ChatResponse>('/api/chat', {
      method: 'POST',
      body: JSON.stringify(req),
    });
  }

  public async getMemories(): Promise<MemoryList> {
    if (this.mockMode) {
      return mockEngine.getMemories();
    }
    return this.request<MemoryList>('/api/memories', {
      method: 'GET',
    });
  }

  public async updateMemorySettings(enabled: boolean): Promise<MemoryList> {
    if (this.mockMode) {
      return mockEngine.updateMemorySettings(enabled);
    }
    return this.request<MemoryList>('/api/memories/settings', {
      method: 'PUT',
      body: JSON.stringify({ enabled }),
    });
  }

  public async saveMemory(key: MemoryKey, value: string): Promise<MemoryItem> {
    if (this.mockMode) {
      return mockEngine.saveMemory(key, value);
    }
    return this.request<MemoryItem>(`/api/memories/${encodeURIComponent(key)}`, {
      method: 'PUT',
      body: JSON.stringify({ value }),
    });
  }

  public async deleteMemory(id: string): Promise<OkResponse> {
    if (this.mockMode) {
      return mockEngine.deleteMemory(id);
    }
    return this.request<OkResponse>(`/api/memories/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    });
  }

  public async clearMemories(): Promise<OkResponse> {
    if (this.mockMode) {
      return mockEngine.clearMemories();
    }
    return this.request<OkResponse>('/api/memories', {
      method: 'DELETE',
    });
  }
}

export const apiClient = new ApiClient();
