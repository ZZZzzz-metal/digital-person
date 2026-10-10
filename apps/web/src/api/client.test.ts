import { describe, it, expect, beforeEach } from 'vitest';
import { ApiClient, ApiError } from './client';
import { mockEngine } from './mock';
import { formatBeijingTime, MEMORY_KEY_LABELS, EMOTION_LABELS, EXPRESSION_LABELS } from './types';

describe('Shared Types and Formatters', () => {
  it('formats UTC ISO timestamp to Beijing Time (UTC+8)', () => {
    // 2026-10-10T12:00:00Z 对应北京时间 2026-10-10 20:00:00
    const beijing = formatBeijingTime('2026-10-10T12:00:00Z');
    expect(beijing).toBe('2026-10-10 20:00:00');
  });

  it('has valid labels for memory keys, emotions, expressions', () => {
    expect(MEMORY_KEY_LABELS.exam_subject).toBe('关注考试科目');
    expect(EMOTION_LABELS.anxious).toBe('焦虑');
    expect(EXPRESSION_LABELS.concern).toBe('关切倾听');
  });
});

describe('MockEngine Service & ApiClient in Mock Mode', () => {
  let client: ApiClient;

  beforeEach(() => {
    mockEngine.resetToDefault();
    client = new ApiClient(true);
  });

  it('checks health status in mock mode', async () => {
    const health = await client.getHealth();
    expect(health.status).toBe('ok');
    expect(health.model_ready).toBe(true);
    expect(health.is_mock).toBe(true);
    expect(health.model_version).toBe('mock-web-v1');
  });

  it('handles session lifecycle (create, list, messages, delete)', async () => {
    const session = await client.createSession('测试会话');
    expect(session.title).toBe('测试会话');
    expect(session.id).toBeDefined();

    const list = await client.listSessions();
    expect(list.some((s) => s.id === session.id)).toBe(true);

    const messages = await client.getSessionMessages(session.id);
    expect(messages.length).toBeGreaterThanOrEqual(1);

    const delRes = await client.deleteSession(session.id);
    expect(delRes.ok).toBe(true);

    await expect(client.getSessionMessages(session.id)).rejects.toMatchObject({
      status: 404,
      error: { code: 'NOT_FOUND' },
    });
  });

  it('handles chat with emotion and memory candidate retrieval', async () => {
    const session = await client.createSession('备考交流');

    // 表达焦虑，触发 concern 表情与高数记忆检索
    const resp1 = await client.sendChat({
      session_id: session.id,
      client_turn_id: 'turn-test-1',
      text: '我一想到考试就特别紧张焦虑。',
    });

    expect(resp1.is_mock).toBe(true);
    expect(resp1.emotion).toBe('anxious');
    expect(resp1.expression).toBe('concern');
    expect(resp1.retrieved_memories.some((m) => m.key === 'exam_subject')).toBe(true);

    // 幂等性测试：相同的 (session_id, client_turn_id) 返回原响应
    const resp1Repeat = await client.sendChat({
      session_id: session.id,
      client_turn_id: 'turn-test-1',
      text: '我一想到考试就特别紧张焦虑。',
    });
    expect(resp1Repeat.reply).toBe(resp1.reply);
  });

  it('handles memory CRUD and enabled switch correctly', async () => {
    // 初始状态包含默认记忆
    const mems = await client.getMemories();
    expect(mems.enabled).toBe(true);
    expect(mems.items.length).toBeGreaterThan(0);

    // 保存/纠正记忆：将 exam_subject 更新为 线性代数
    const updated = await client.saveMemory('exam_subject', '线性代数');
    expect(updated.key).toBe('exam_subject');
    expect(updated.value).toBe('线性代数');

    const memsAfter = await client.getMemories();
    const found = memsAfter.items.find((m) => m.key === 'exam_subject');
    expect(found?.value).toBe('线性代数');

    // 关闭记忆：列表应返回空数组，并不允许新建记忆 (409)
    await client.updateMemorySettings(false);
    const disabledList = await client.getMemories();
    expect(disabledList.enabled).toBe(false);
    expect(disabledList.items).toEqual([]);

    await expect(client.saveMemory('hobby', '摄影')).rejects.toMatchObject({
      status: 409,
      error: { code: 'MEMORY_DISABLED' },
    });

    // 重新开启记忆：之前的事实仍在
    await client.updateMemorySettings(true);
    const enabledList = await client.getMemories();
    expect(enabledList.enabled).toBe(true);
    expect(enabledList.items.some((m) => m.value === '线性代数')).toBe(true);

    // 清空记忆
    await client.clearMemories();
    const emptyList = await client.getMemories();
    expect(emptyList.items).toEqual([]);
  });

  it('rejects invalid inputs with 400', async () => {
    await expect(client.saveMemory('hobby', '   ')).rejects.toMatchObject({
      status: 400,
      error: { code: 'INVALID_REQUEST' },
    });

    const session = await client.createSession('测试400');
    await expect(
      client.sendChat({
        session_id: session.id,
        client_turn_id: 'turn-blank',
        text: '    ',
      })
    ).rejects.toMatchObject({
      status: 400,
      error: { code: 'INVALID_REQUEST' },
    });
  });

  it('simulates 503 and 409 errors without falling back to fake replies', async () => {
    mockEngine.simulate503 = true;
    const session = await client.createSession('异常测试');

    await expect(
      client.sendChat({
        session_id: session.id,
        client_turn_id: 'turn-503',
        text: '你好',
      })
    ).rejects.toMatchObject({
      status: 503,
      error: { code: 'MODEL_UNAVAILABLE' },
    });

    mockEngine.simulate503 = false;
    mockEngine.simulate409 = true;

    await expect(
      client.sendChat({
        session_id: session.id,
        client_turn_id: 'turn-409',
        text: '你好',
      })
    ).rejects.toMatchObject({
      status: 409,
      error: { code: 'TURN_IN_PROGRESS' },
    });
  });
});

describe('Real ApiClient error handling', () => {
  it('throws ApiError without falling back to mock when offline', async () => {
    const realClient = new ApiClient(false); // 强制真实模式
    expect(realClient.isMock()).toBe(false);

    // 当请求不存在或网络不通时，必须抛出 ApiError，不能静默返回 mock 数据
    await expect(realClient.getHealth()).rejects.toThrow(ApiError);
  });
});
