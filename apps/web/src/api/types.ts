/**
 * B2 综合情感陪伴对话模型 前端共享数据类型
 * 严格遵从 docs/分工/00-总约定.md §5、§8 及 contracts/schema/。
 */

export type Emotion = 'neutral' | 'happy' | 'sad' | 'anxious' | 'angry' | 'unknown';
export type Expression = 'neutral' | 'smile' | 'concern' | 'listening';
export type MemoryKey = 'preferred_name' | 'study_goal' | 'exam_subject' | 'response_preference' | 'hobby';

export interface Message {
  role: 'user' | 'assistant';
  content: string;
}

export interface MemoryItem {
  id: string;
  key: MemoryKey;
  value: string;
  updated_at: string; // ISO 8601 UTC 时间，以 Z 结尾
}

export interface MemoryContext {
  prompt_text: string;
  retrieved_memories: MemoryItem[];
}

export interface MemoryList {
  enabled: boolean;
  items: MemoryItem[];
}

export interface MemorySettings {
  enabled: boolean;
}

export interface MemorySave {
  value: string;
}

export interface SessionDTO {
  id: string;
  title: string;
  created_at: string; // ISO 8601 UTC 时间，以 Z 结尾
}

export interface SessionCreate {
  title?: string;
}

export interface ChatRequest {
  session_id: string;
  client_turn_id: string;
  text: string;
}

export interface ChatResponse {
  session_id: string;
  client_turn_id: string;
  reply: string;
  emotion: Emotion;
  expression: Expression;
  retrieved_memories: MemoryItem[];
  model_version: string;
  elapsed_ms: number;
  is_mock: boolean;
}

export interface Health {
  status: 'ok' | 'degraded';
  model_ready: boolean;
  is_mock: boolean;
  model_version: string;
}

export interface ErrorDetail {
  code: string;
  message: string;
}

export interface ErrorResponse {
  error: ErrorDetail;
}

export interface OkResponse {
  ok: true;
}

export const MEMORY_KEY_LABELS: Record<MemoryKey, string> = {
  preferred_name: '称呼',
  study_goal: '学习目标',
  exam_subject: '关注考试科目',
  response_preference: '回应偏好',
  hobby: '兴趣爱好',
};

export const EMOTION_LABELS: Record<Emotion, string> = {
  neutral: '平静',
  happy: '开心',
  sad: '低落',
  anxious: '焦虑',
  angry: '愤怒',
  unknown: '未知',
};

export const EXPRESSION_LABELS: Record<Expression, string> = {
  neutral: '平静注视',
  smile: '微笑陪伴',
  concern: '关切倾听',
  listening: '专注倾听',
};

/**
 * 将后端返回的 UTC ISO 8601 时间转换为北京时间展示 (UTC+8)
 * 格式：YYYY-MM-DD HH:mm:ss
 */
export function formatBeijingTime(utcIso: string): string {
  if (!utcIso) return '';
  const date = new Date(utcIso);
  if (isNaN(date.getTime())) return utcIso;

  // 使用 Intl.DateTimeFormat 固定时区为 Asia/Shanghai
  const formatter = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });

  const parts = formatter.formatToParts(date);
  const partMap: Record<string, string> = {};
  for (const part of parts) {
    partMap[part.type] = part.value;
  }

  return `${partMap.year}-${partMap.month}-${partMap.day} ${partMap.hour}:${partMap.minute}:${partMap.second}`;
}
