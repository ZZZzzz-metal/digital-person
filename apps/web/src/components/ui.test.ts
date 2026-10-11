import { describe, it, expect } from 'vitest';
import {
  Emotion,
  Expression,
  MemoryKey,
  EMOTION_LABELS,
  EXPRESSION_LABELS,
  MEMORY_KEY_LABELS,
  formatBeijingTime,
} from '../api/types';
import { mockEngine } from '../api/mock';
import { KEY_PLACEHOLDERS } from './MemoryPanel';

describe('UI Design System Constants & Consistency', () => {
  it('covers all 4 digital person expressions with human readable labels', () => {
    const requiredExpressions: Expression[] = ['neutral', 'smile', 'concern', 'listening'];
    for (const exp of requiredExpressions) {
      expect(EXPRESSION_LABELS[exp]).toBeDefined();
      expect(typeof EXPRESSION_LABELS[exp]).toBe('string');
    }
    expect(EXPRESSION_LABELS.neutral).toBe('平静注视');
    expect(EXPRESSION_LABELS.smile).toBe('微笑陪伴');
    expect(EXPRESSION_LABELS.concern).toBe('关切倾听');
    expect(EXPRESSION_LABELS.listening).toBe('专注倾听');
  });

  it('covers emotion labels mapping', () => {
    const requiredEmotions: Emotion[] = ['neutral', 'happy', 'sad', 'anxious', 'angry', 'unknown'];
    for (const em of requiredEmotions) {
      expect(EMOTION_LABELS[em]).toBeDefined();
    }
    expect(EMOTION_LABELS.happy).toBe('开心');
    expect(EMOTION_LABELS.anxious).toBe('焦虑');
  });

  it('covers all 5 whitelist long-term memory keys', () => {
    const requiredKeys: MemoryKey[] = [
      'preferred_name',
      'study_goal',
      'exam_subject',
      'response_preference',
      'hobby',
    ];
    for (const key of requiredKeys) {
      expect(MEMORY_KEY_LABELS[key]).toBeDefined();
    }
    expect(MEMORY_KEY_LABELS.preferred_name).toBe('称呼');
    expect(MEMORY_KEY_LABELS.study_goal).toBe('学习目标');
    expect(MEMORY_KEY_LABELS.exam_subject).toBe('关注考试科目');
    expect(MEMORY_KEY_LABELS.response_preference).toBe('回应偏好');
    expect(MEMORY_KEY_LABELS.hobby).toBe('兴趣爱好');
  });

  it('formats Beijing time correctly across year and leap year dates', () => {
    expect(formatBeijingTime('2026-10-10T00:00:00Z')).toBe('2026-10-10 08:00:00');
    expect(formatBeijingTime('2026-02-28T16:00:00Z')).toBe('2026-03-01 00:00:00');
    expect(formatBeijingTime('')).toBe('');
    expect(formatBeijingTime('invalid-date')).toBe('invalid-date');
  });

  it('covers all 5 whitelist memory key placeholders for rich user input guidance', () => {
    const requiredKeys: MemoryKey[] = [
      'preferred_name',
      'study_goal',
      'exam_subject',
      'response_preference',
      'hobby',
    ];
    for (const key of requiredKeys) {
      expect(KEY_PLACEHOLDERS[key]).toBeDefined();
      expect(KEY_PLACEHOLDERS[key].length).toBeGreaterThan(0);
      expect(KEY_PLACEHOLDERS[key]).toContain('如：');
    }
  });

  it('verifies mockEngine state transitions for simulation toggles', async () => {
    mockEngine.resetToDefault();
    expect(mockEngine.simulate503).toBe(false);
    expect(mockEngine.simulate409).toBe(false);

    mockEngine.simulate503 = true;
    const health1 = await mockEngine.getHealth();
    expect(health1.status).toBe('degraded');
    expect(health1.model_ready).toBe(false);

    mockEngine.resetToDefault();
    expect(mockEngine.simulate503).toBe(false);
    const health2 = await mockEngine.getHealth();
    expect(health2.status).toBe('ok');
    expect(health2.model_ready).toBe(true);
  });
});
