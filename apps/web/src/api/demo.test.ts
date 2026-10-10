import { describe, it, expect, beforeEach } from 'vitest';
import examScenario from '../../../../data/demo/exam-memory.json';
import roommateScenario from '../../../../data/demo/roommate-switch.json';
import positiveScenario from '../../../../data/demo/positive-chat.json';
import { mockEngine } from './mock';
import { ApiClient } from './client';
import { MemoryKey } from './types';

describe('Demo Scenarios Execution in Mock Mode (C4 Verification)', () => {
  let client: ApiClient;

  beforeEach(() => {
    mockEngine.resetToDefault();
    client = new ApiClient(true);
  });

  it('runs exam-memory.json scenario: anxiety, memory retrieval, and correction to linear algebra', async () => {
    const session = await client.createSession(examScenario.title);

    // 预置记忆: exam_subject = 高数
    for (const mem of examScenario.memory_setup) {
      await client.saveMemory(mem.key as MemoryKey, mem.value);
    }

    // 轮次 1: 表达考试紧张
    const res1 = await client.sendChat({
      session_id: session.id,
      client_turn_id: 'turn-exam-1',
      text: examScenario.turns[0].text,
    });
    expect(res1.emotion).toBe('anxious');
    expect(res1.expression).toBe('concern');
    expect(res1.is_mock).toBe(true);

    // 轮次 2: 提到昨天考试，命中高数记忆
    const res2 = await client.sendChat({
      session_id: session.id,
      client_turn_id: 'turn-exam-2',
      text: examScenario.turns[1].text,
    });
    expect(res2.retrieved_memories.some((m) => m.key === 'exam_subject' && m.value.includes('高数'))).toBe(true);
    expect(res2.reply).toContain('高数');

    // 轮次 3: 用户说明记错了，界面引导纠正为线代
    const res3 = await client.sendChat({
      session_id: session.id,
      client_turn_id: 'turn-exam-3',
      text: examScenario.turns[2].text,
    });
    expect(res3.reply).toContain('线性代数');

    // 用户主动点击确认纠正记忆为 线性代数
    const updated = await client.saveMemory('exam_subject', '线性代数');
    expect(updated.value).toBe('线性代数');

    // 轮次 4: 追问是否记得，准确回答 线性代数，不再是高数
    const res4 = await client.sendChat({
      session_id: session.id,
      client_turn_id: 'turn-exam-4',
      text: examScenario.turns[3].text,
    });
    expect(res4.retrieved_memories.some((m) => m.key === 'exam_subject' && m.value.includes('线性代数'))).toBe(true);
    expect(res4.reply).toContain('线性代数');
    expect(res4.reply).not.toContain('高等数学');
  });

  it('runs roommate-switch.json scenario: roommate friction, topic switch, and smile closure', async () => {
    const session = await client.createSession(roommateScenario.title);

    for (const mem of roommateScenario.memory_setup) {
      await client.saveMemory(mem.key as MemoryKey, mem.value);
    }

    // 轮次 1: 宿舍矛盾倾诉，专注倾听，不强加学习目标
    const res1 = await client.sendChat({
      session_id: session.id,
      client_turn_id: 'turn-room-1',
      text: roommateScenario.turns[0].text,
    });
    expect(res1.expression).toBe('listening');
    expect(res1.retrieved_memories.filter((m) => m.key === 'study_goal')).toHaveLength(0);

    // 轮次 2: 切换到英语六级计划
    const res2 = await client.sendChat({
      session_id: session.id,
      client_turn_id: 'turn-room-2',
      text: roommateScenario.turns[1].text,
    });
    expect(res2.retrieved_memories.some((m) => m.key === 'study_goal')).toBe(true);
    expect(res2.reply).toContain('六级');

    // 轮次 3: 探讨背 50 个单词
    const res3 = await client.sendChat({
      session_id: session.id,
      client_turn_id: 'turn-room-3',
      text: roommateScenario.turns[2].text,
    });
    expect(res3.expression).toBe('listening');
    expect(res3.reply).toContain('50个单词');

    // 轮次 4: 心情好转致谢，表情切换为 smile
    const res4 = await client.sendChat({
      session_id: session.id,
      client_turn_id: 'turn-room-4',
      text: roommateScenario.turns[3].text,
    });
    expect(res4.emotion).toBe('happy');
    expect(res4.expression).toBe('smile');
  });

  it('runs positive-chat.json scenario: achievement, praise, sunset photography, and smile expression', async () => {
    const session = await client.createSession(positiveScenario.title);

    for (const mem of positiveScenario.memory_setup) {
      await client.saveMemory(mem.key as MemoryKey, mem.value);
    }

    // 轮次 1: 大作业拿第一名被老师夸
    const res1 = await client.sendChat({
      session_id: session.id,
      client_turn_id: 'turn-pos-1',
      text: positiveScenario.turns[0].text,
    });
    expect(res1.emotion).toBe('happy');
    expect(res1.expression).toBe('smile');

    // 轮次 2: 熬夜剪辑三天被认可
    const res2 = await client.sendChat({
      session_id: session.id,
      client_turn_id: 'turn-pos-2',
      text: positiveScenario.turns[1].text,
    });
    expect(res2.emotion).toBe('happy');
    expect(res2.expression).toBe('smile');
    expect(res2.retrieved_memories.some((m) => m.key === 'hobby')).toBe(true);

    // 轮次 3: 采风拍落日
    const res3 = await client.sendChat({
      session_id: session.id,
      client_turn_id: 'turn-pos-3',
      text: positiveScenario.turns[2].text,
    });
    expect(res3.emotion).toBe('happy');
    expect(res3.expression).toBe('smile');
    expect(res3.retrieved_memories.some((m) => m.key === 'hobby')).toBe(true);

    // 轮次 4: 后续督促期待
    const res4 = await client.sendChat({
      session_id: session.id,
      client_turn_id: 'turn-pos-4',
      text: positiveScenario.turns[3].text,
    });
    expect(res4.emotion).toBe('happy');
    expect(res4.expression).toBe('smile');
  });
});
