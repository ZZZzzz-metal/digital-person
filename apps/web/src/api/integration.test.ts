import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { spawn, ChildProcess } from 'node:child_process';
import path from 'node:path';
import { ApiClient } from './client';

describe('Real FastAPI Backend Integration Tests', () => {
  let backendProc: ChildProcess | null = null;
  const testPort = 8011;
  const baseUrl = `http://127.0.0.1:${testPort}`;
  const repoRoot = path.resolve(__dirname, '../../../../');

  beforeAll(async () => {
    // 启动本地 FastAPI 后端 (B2_MODE=stub 模式进行契约与跨源集成测试)
    backendProc = spawn(
      'py',
      ['-3.12', '-m', 'uvicorn', 'server.app:app', '--host', '127.0.0.1', '--port', String(testPort)],
      {
        cwd: repoRoot,
        env: {
          ...process.env,
          PYTHONPATH: path.join(repoRoot, 'src'),
          B2_MODE: 'stub',
          B2_DB_PATH: path.join(repoRoot, '.runtime', 'test_int.sqlite3'),
        },
        stdio: 'pipe',
      }
    );

    // 等待服务健康检查可用（最多等待 8 秒）
    let ready = false;
    for (let i = 0; i < 40; i++) {
      try {
        const res = await fetch(`${baseUrl}/health`);
        if (res.ok) {
          ready = true;
          break;
        }
      } catch {
        // 继续等待
      }
      await new Promise((r) => setTimeout(r, 200));
    }

    if (!ready) {
      throw new Error(`FastAPI 后端在端口 ${testPort} 启动超时`);
    }
  }, 15000);

  afterAll(() => {
    if (backendProc && !backendProc.killed) {
      backendProc.kill();
    }
  });

  it('connects to real FastAPI health endpoint via ApiClient in real mode', async () => {
    const client = new ApiClient(false, baseUrl);
    expect(client.isMock()).toBe(false);

    const health = await client.getHealth();
    expect(health.status).toBe('ok');
    expect(health.model_ready).toBe(true);
    expect(health.is_mock).toBe(true); // Stub engine 明确声明 is_mock: true
    expect(health.model_version).toBe('stub-b1');
  });

  it('runs full session lifecycle and verifies b2_anon cookie persistence with real backend', async () => {
    const client = new ApiClient(false, baseUrl);

    // 1. 创建会话
    const session = await client.createSession('端到端集成会话');
    expect(session.id).toBeDefined();
    expect(session.title).toBe('端到端集成会话');
    expect(client.getSessionCookie()).toContain('b2_anon=');

    // 2. 列出会话（通过 b2_anon cookie 关联）
    const sessions = await client.listSessions();
    expect(sessions.some((s) => s.id === session.id)).toBe(true);

    // 3. 初始消息列表为空
    const msgs = await client.getSessionMessages(session.id);
    expect(msgs).toEqual([]);

    // 4. 发送聊天消息
    const chatRes = await client.sendChat({
      session_id: session.id,
      client_turn_id: 'turn-real-int-1',
      text: '你好，伴学助手！',
    });
    expect(chatRes.session_id).toBe(session.id);
    expect(chatRes.client_turn_id).toBe('turn-real-int-1');
    expect(chatRes.reply).toContain('【演示数据】');
    expect(chatRes.is_mock).toBe(true);

    // 5. 幂等性：同 session_id + client_turn_id 再次发送返回相同响应
    const chatRepeat = await client.sendChat({
      session_id: session.id,
      client_turn_id: 'turn-real-int-1',
      text: '你好，伴学助手！',
    });
    expect(chatRepeat.reply).toBe(chatRes.reply);

    // 6. 成功对话写入 2 条历史记录 (user + assistant)
    const msgsAfter = await client.getSessionMessages(session.id);
    expect(msgsAfter).toHaveLength(2);
    expect(msgsAfter[0].role).toBe('user');
    expect(msgsAfter[1].role).toBe('assistant');

    // 7. 保存长期事实记忆（归属当前匿名用户）
    const savedMem = await client.saveMemory('exam_subject', '高等数学');
    expect(savedMem.key).toBe('exam_subject');
    expect(savedMem.value).toBe('高等数学');

    const memList = await client.getMemories();
    expect(memList.enabled).toBe(true);
    expect(memList.items.some((m) => m.key === 'exam_subject' && m.value === '高等数学')).toBe(true);

    // 8. 关闭记忆功能：再次保存应返回 409 MEMORY_DISABLED
    await client.updateMemorySettings(false);
    const disabledList = await client.getMemories();
    expect(disabledList.enabled).toBe(false);
    expect(disabledList.items).toEqual([]);

    await expect(client.saveMemory('hobby', '摄影')).rejects.toMatchObject({
      status: 409,
      code: 'MEMORY_DISABLED',
    });

    // 重新开启记忆
    await client.updateMemorySettings(true);

    // 9. 删除会话：会话与消息清理，但长期事实记忆保留
    const delRes = await client.deleteSession(session.id);
    expect(delRes.ok).toBe(true);

    const memsStillExist = await client.getMemories();
    expect(memsStillExist.items.some((m) => m.value === '高等数学')).toBe(true);

    // 清空记忆
    await client.clearMemories();
    const finalMems = await client.getMemories();
    expect(finalMems.items).toEqual([]);
  });

  it('rejects invalid inputs on real backend with 400 INVALID_REQUEST', async () => {
    const client = new ApiClient(false, baseUrl);
    const session = await client.createSession('测试边界');

    // 空白文本
    await expect(
      client.sendChat({
        session_id: session.id,
        client_turn_id: 'turn-empty',
        text: '   ',
      })
    ).rejects.toMatchObject({
      status: 400,
      code: 'INVALID_REQUEST',
    });
  });
});
