/**
 * 前端纯本地 Mock 引擎与存储模拟
 * 严格按照总约定 §5、§8，所有响应均标记 is_mock: true，并在页面突出显示“演示数据”。
 */

import {
  ChatRequest,
  ChatResponse,
  Emotion,
  Expression,
  Health,
  MemoryItem,
  MemoryKey,
  MemoryList,
  Message,
  OkResponse,
  SessionDTO,
} from './types';

const MOCK_STORAGE_KEY = 'b2_digital_person_mock_data_v1';

interface MockStoreState {
  sessions: SessionDTO[];
  messages: Record<string, Message[]>; // session_id -> Message[]
  turns: Record<string, ChatResponse>; // `${session_id}:${client_turn_id}` -> ChatResponse
  memoryEnabled: boolean;
  memories: MemoryItem[];
}

function getInitialState(): MockStoreState {
  const now = new Date().toISOString();
  const defaultSessionId = 'session-mock-default';
  return {
    sessions: [
      {
        id: defaultSessionId,
        title: '期末复习与倾诉陪伴',
        created_at: now,
      },
    ],
    messages: {
      [defaultSessionId]: [
        {
          role: 'assistant',
          content: '你好呀！我是你的伴学助手。最近学习或生活上有什么想和我聊聊的吗？',
        },
      ],
    },
    turns: {},
    memoryEnabled: true,
    memories: [
      {
        id: 'mem-mock-1',
        key: 'preferred_name',
        value: '小航',
        updated_at: now,
      },
      {
        id: 'mem-mock-2',
        key: 'exam_subject',
        value: '高等数学',
        updated_at: now,
      },
    ],
  };
}

export class MockEngineService {
  private state: MockStoreState;
  public simulate503: boolean = false;
  public simulate409: boolean = false;

  constructor() {
    this.state = this.loadState();
  }

  private loadState(): MockStoreState {
    try {
      const saved = localStorage.getItem(MOCK_STORAGE_KEY);
      if (saved) {
        return JSON.parse(saved);
      }
    } catch {
      // 忽略无法读取 localStorage 的异常（如隐私模式或测试环境）
    }
    return getInitialState();
  }

  private persistState() {
    try {
      localStorage.setItem(MOCK_STORAGE_KEY, JSON.stringify(this.state));
    } catch {
      // 忽略环境写入异常
    }
  }

  public resetToDefault(): void {
    this.state = getInitialState();
    this.simulate503 = false;
    this.simulate409 = false;
    this.persistState();
  }

  public async getHealth(): Promise<Health> {
    if (this.simulate503) {
      return {
        status: 'degraded',
        model_ready: false,
        is_mock: true,
        model_version: 'mock-web-v1',
      };
    }
    return {
      status: 'ok',
      model_ready: true,
      is_mock: true,
      model_version: 'mock-web-v1',
    };
  }

  public async listSessions(): Promise<SessionDTO[]> {
    return [...this.state.sessions];
  }

  public async createSession(title?: string): Promise<SessionDTO> {
    const id = `session-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
    const sessionTitle = (title && title.trim()) ? title.trim().slice(0, 100) : '新会话';
    const newSession: SessionDTO = {
      id,
      title: sessionTitle,
      created_at: new Date().toISOString(),
    };
    this.state.sessions.unshift(newSession);
    this.state.messages[id] = [
      {
        role: 'assistant',
        content: '你好呀！我是你的伴学助手。有什么心事随时跟我说说～',
      },
    ];
    this.persistState();
    return newSession;
  }

  public async getSessionMessages(sessionId: string): Promise<Message[]> {
    const msgs = this.state.messages[sessionId];
    if (!msgs) {
      throw {
        status: 404,
        error: { code: 'NOT_FOUND', message: '会话不存在或已被删除' },
      };
    }
    return [...msgs];
  }

  public async deleteSession(sessionId: string): Promise<OkResponse> {
    this.state.sessions = this.state.sessions.filter((s) => s.id !== sessionId);
    delete this.state.messages[sessionId];
    // 删除相关 turns 缓存
    for (const k of Object.keys(this.state.turns)) {
      if (k.startsWith(`${sessionId}:`)) {
        delete this.state.turns[k];
      }
    }
    this.persistState();
    return { ok: true };
  }

  public async getMemories(): Promise<MemoryList> {
    if (!this.state.memoryEnabled) {
      return {
        enabled: false,
        items: [],
      };
    }
    return {
      enabled: true,
      items: [...this.state.memories],
    };
  }

  public async updateMemorySettings(enabled: boolean): Promise<MemoryList> {
    this.state.memoryEnabled = enabled;
    this.persistState();
    return {
      enabled,
      items: enabled ? [...this.state.memories] : [],
    };
  }

  public async saveMemory(key: MemoryKey, value: string): Promise<MemoryItem> {
    if (!this.state.memoryEnabled) {
      throw {
        status: 409,
        error: { code: 'MEMORY_DISABLED', message: '记忆功能已关闭，无法保存新记忆' },
      };
    }
    const cleanVal = (value || '').trim();
    if (!cleanVal || cleanVal.length > 200) {
      throw {
        status: 400,
        error: { code: 'INVALID_REQUEST', message: '记忆内容不能为空且不超过 200 字' },
      };
    }

    const existingIndex = this.state.memories.findIndex((m) => m.key === key);
    const now = new Date().toISOString();
    let item: MemoryItem;

    if (existingIndex >= 0) {
      item = {
        ...this.state.memories[existingIndex],
        value: cleanVal,
        updated_at: now,
      };
      this.state.memories[existingIndex] = item;
    } else {
      item = {
        id: `mem-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`,
        key,
        value: cleanVal,
        updated_at: now,
      };
      this.state.memories.push(item);
    }

    this.persistState();
    return item;
  }

  public async deleteMemory(id: string): Promise<OkResponse> {
    this.state.memories = this.state.memories.filter((m) => m.id !== id);
    this.persistState();
    return { ok: true };
  }

  public async clearMemories(): Promise<OkResponse> {
    this.state.memories = [];
    this.persistState();
    return { ok: true };
  }

  public async sendChat(req: ChatRequest): Promise<ChatResponse> {
    if (this.simulate503) {
      throw {
        status: 503,
        error: { code: 'MODEL_UNAVAILABLE', message: '模拟模型服务暂不可用 (503)' },
      };
    }

    if (this.simulate409) {
      throw {
        status: 409,
        error: { code: 'TURN_IN_PROGRESS', message: '当前会话有正在生成的请求 (409)' },
      };
    }

    if (!req.session_id) {
      throw {
        status: 400,
        error: { code: 'INVALID_REQUEST', message: '缺少 session_id' },
      };
    }

    const session = this.state.sessions.find((s) => s.id === req.session_id);
    if (!session) {
      throw {
        status: 404,
        error: { code: 'NOT_FOUND', message: '所选会话不存在' },
      };
    }

    const text = (req.text || '').trim();
    if (!text || text.length > 2000) {
      throw {
        status: 400,
        error: { code: 'INVALID_REQUEST', message: '文本不能为空且不超过 2000 字符' },
      };
    }

    // 检查幂等性缓存：(session_id, client_turn_id)
    const turnKey = `${req.session_id}:${req.client_turn_id}`;
    if (this.state.turns[turnKey]) {
      return this.state.turns[turnKey];
    }

    // 检索与当前输入相关的记忆
    const activeMemories = this.state.memoryEnabled ? this.state.memories : [];
    const matchedMemories: MemoryItem[] = [];

    const examMem = activeMemories.find((m) => m.key === 'exam_subject');
    const nameMem = activeMemories.find((m) => m.key === 'preferred_name');
    const goalMem = activeMemories.find((m) => m.key === 'study_goal');
    const hobbyMem = activeMemories.find((m) => m.key === 'hobby');

    if (examMem && (text.includes('考试') || text.includes('科目') || text.includes('高数') || text.includes('线代') || text.includes(examMem.value))) {
      matchedMemories.push(examMem);
    }
    if (nameMem && (text.includes('称呼') || text.includes('我叫') || text.includes('名字') || text.includes(nameMem.value))) {
      matchedMemories.push(nameMem);
    }
    if (goalMem && (text.includes('目标') || text.includes('计划') || text.includes(goalMem.value))) {
      matchedMemories.push(goalMem);
    }
    if (hobbyMem && (text.includes('爱好') || text.includes('喜欢') || text.includes(hobbyMem.value))) {
      matchedMemories.push(hobbyMem);
    }

    // 产生智能 Mock 回复与情绪表情映射
    let replyText = '';
    let emotion: Emotion = 'neutral';
    let expression: Expression = 'listening';

    if (text.includes('线代') && (text.includes('错') || text.includes('改') || text.includes('其实'))) {
      emotion = 'neutral';
      expression = 'listening';
      replyText = '收到了！你刚才更正为线性代数啦。右侧记忆卡片已为你准备好，你可以点击“保存/修改”确认更新记忆哦。';
    } else if (text.includes('记得') && (text.includes('考试') || text.includes('哪门'))) {
      if (examMem) {
        emotion = 'neutral';
        expression = 'listening';
        replyText = `我当然记得啦，你之前告诉我你正在为【${examMem.value}】复习备考呢。现在的复习节奏感觉怎么样？`;
      } else {
        emotion = 'neutral';
        expression = 'listening';
        replyText = '我这里暂时没有记录你具体关注的考试科目呢。你愿意在右侧记忆栏告诉我吗？';
      }
    } else if (text.includes('紧张') || text.includes('焦虑') || text.includes('压力') || text.includes('担心') || text.includes('怕')) {
      emotion = 'anxious';
      expression = 'concern';
      const subjectMention = examMem ? `关于${examMem.value}，` : '';
      replyText = `听起来你心里有些沉重。${subjectMention}感到紧张焦虑是很多同学都会经历的正常反应，你愿意先跟我说说具体哪一部分最让你感到困扰吗？`;
    } else if (text.includes('难过') || text.includes('伤心') || text.includes('低落') || text.includes('哭') || text.includes('失落')) {
      emotion = 'sad';
      expression = 'concern';
      replyText = '抱抱你，别一个人扛着。如果心里难受，尽管在这里说出来，我会一直在这里陪着你、认真听你说。';
    } else if (text.includes('开心') || text.includes('通过') || text.includes('考完') || text.includes('成功') || text.includes('太棒') || text.includes('太好')) {
      emotion = 'happy';
      expression = 'smile';
      replyText = '太棒啦！真为你感到高兴！看到你付出努力有了回报，这种踏实和喜悦特别值得好好庆祝一下～';
    } else if (text.includes('生气') || text.includes('烦死') || text.includes('吵架') || text.includes('室友') || text.includes('矛盾')) {
      emotion = 'angry';
      expression = 'listening';
      replyText = '遇到宿舍或相处上的摩擦确实容易让人又烦又委屈。别憋在心里，先深呼吸一口气，跟我吐槽吐槽发生了什么。';
    } else {
      emotion = 'neutral';
      expression = 'listening';
      const greetingName = nameMem ? `${nameMem.value}，` : '';
      replyText = `${greetingName}我听到你说的话了。无论遇到什么事，你都可以随时跟我聊，我们一步一步来理清它。`;
    }

    const response: ChatResponse = {
      session_id: req.session_id,
      client_turn_id: req.client_turn_id,
      reply: replyText,
      emotion,
      expression,
      retrieved_memories: matchedMemories,
      model_version: 'mock-web-v1',
      elapsed_ms: 120 + Math.floor(Math.random() * 80),
      is_mock: true,
    };

    // 保存消息记录
    if (!this.state.messages[req.session_id]) {
      this.state.messages[req.session_id] = [];
    }
    this.state.messages[req.session_id].push({
      role: 'user',
      content: text,
    });
    this.state.messages[req.session_id].push({
      role: 'assistant',
      content: replyText,
    });

    this.state.turns[turnKey] = response;
    this.persistState();

    return response;
  }
}

export const mockEngine = new MockEngineService();
