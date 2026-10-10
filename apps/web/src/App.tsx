import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  ChatResponse,
  Emotion,
  Expression,
  Health,
  MemoryItem,
  MemoryKey,
  Message,
  SessionDTO,
} from './api/types';
import { ApiClient, ApiError } from './api/client';
import { mockEngine } from './api/mock';
import { Header } from './components/Header';
import { AvatarDisplay } from './components/AvatarDisplay';
import { SessionList } from './components/SessionList';
import { ChatWindow } from './components/ChatWindow';
import { MemoryPanel } from './components/MemoryPanel';

interface PendingTurn {
  sessionId: string;
  clientTurnId: string;
  text: string;
  status: 'sending' | 'failed';
  errorMessage?: string;
}

export const App: React.FC = () => {
  const clientRef = useRef<ApiClient>(new ApiClient());
  const client = clientRef.current;

  const [isMockMode, setIsMockMode] = useState<boolean>(client.isMock());
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);

  // 会话与消息状态
  const [sessions, setSessions] = useState<SessionDTO[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const activeSessionIdRef = useRef<string | null>(null);
  activeSessionIdRef.current = activeSessionId;

  const [messages, setMessages] = useState<Message[]>([]);
  const [responseMetaMap, setResponseMetaMap] = useState<Record<number, ChatResponse>>({});

  // 发送中/失败状态：按 session_id 隔离，防止切换会话后污染其他会话
  const [pendingTurns, setPendingTurns] = useState<Record<string, PendingTurn>>({});

  // 记忆状态
  const [memoryEnabled, setMemoryEnabled] = useState<boolean>(true);
  const [memories, setMemories] = useState<MemoryItem[]>([]);

  // 数字人状态
  const [currentExpression, setCurrentExpression] = useState<Expression>('neutral');
  const [currentEmotion, setCurrentEmotion] = useState<Emotion>('neutral');
  const [currentModelVersion, setCurrentModelVersion] = useState<string>('baseline-v1');
  const [lastElapsedMs, setLastElapsedMs] = useState<number | undefined>(undefined);
  const [lastIsMock, setLastIsMock] = useState<boolean>(isMockMode);

  // Mock 调试模拟开关
  const [simulate503, setSimulate503] = useState<boolean>(false);
  const [simulate409, setSimulate409] = useState<boolean>(false);

  // 1. 获取健康状态
  const refreshHealth = useCallback(async () => {
    try {
      const h = await client.getHealth();
      setHealth(h);
      setHealthError(null);
      setCurrentModelVersion(h.model_version);
      setLastIsMock(h.is_mock);
    } catch (err: unknown) {
      setHealth(null);
      setHealthError(err instanceof Error ? err.message : '连接后端失败');
    }
  }, [client]);

  // 2. 加载会话列表
  const loadSessions = useCallback(async () => {
    try {
      const list = await client.listSessions();
      setSessions(list);
      if (list.length > 0 && !activeSessionId) {
        setActiveSessionId(list[0].id);
      }
    } catch (err: unknown) {
      console.error('加载会话失败:', err);
    }
  }, [client, activeSessionId]);

  // 3. 加载记忆
  const loadMemories = useCallback(async () => {
    try {
      const res = await client.getMemories();
      setMemoryEnabled(res.enabled);
      setMemories(res.items);
    } catch (err: unknown) {
      console.error('加载记忆失败:', err);
    }
  }, [client]);

  // 4. 加载当前会话消息
  const loadActiveMessages = useCallback(
    async (sessionId: string) => {
      try {
        const msgs = await client.getSessionMessages(sessionId);
        if (activeSessionIdRef.current === sessionId) {
          setMessages(msgs);
          setResponseMetaMap({});
        }
      } catch (err: unknown) {
        if (activeSessionIdRef.current === sessionId) {
          console.error('加载消息失败:', err);
          setMessages([]);
          setResponseMetaMap({});
        }
      }
    },
    [client]
  );

  // 初始化与会话切换
  useEffect(() => {
    refreshHealth();
    loadSessions();
    loadMemories();
  }, [refreshHealth, loadSessions, loadMemories]);

  useEffect(() => {
    if (activeSessionId) {
      loadActiveMessages(activeSessionId);
    } else {
      setMessages([]);
      setResponseMetaMap({});
    }
  }, [activeSessionId, loadActiveMessages]);

  // 切换模式（Mock / 真实）
  const handleToggleMockMode = (mock: boolean) => {
    client.setMock(mock);
    setIsMockMode(mock);
    setPendingTurns({});
    setResponseMetaMap({});
    refreshHealth();
    loadSessions();
    loadMemories();
  };

  // 重置 Mock 演示数据
  const handleResetMockData = () => {
    mockEngine.resetToDefault();
    setSimulate503(false);
    setSimulate409(false);
    refreshHealth();
    loadSessions();
    loadMemories();
  };

  const handleToggle503 = () => {
    mockEngine.simulate503 = !simulate503;
    setSimulate503(!simulate503);
    refreshHealth();
  };

  const handleToggle409 = () => {
    mockEngine.simulate409 = !simulate409;
    setSimulate409(!simulate409);
  };

  // 会话操作
  const handleCreateSession = async (title?: string) => {
    const s = await client.createSession(title);
    setSessions((prev) => [s, ...prev]);
    setActiveSessionId(s.id);
  };

  const handleDeleteSession = async (id: string) => {
    await client.deleteSession(id);
    setSessions((prev) => prev.filter((s) => s.id !== id));
    setPendingTurns((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
    if (activeSessionId === id) {
      const remaining = sessions.filter((s) => s.id !== id);
      const nextId = remaining.length > 0 ? remaining[0].id : null;
      setActiveSessionId(nextId);
      if (!nextId) {
        setMessages([]);
        setResponseMetaMap({});
      }
    }
  };

  // 发送消息
  const handleSendMessage = async (text: string, existingTurnId?: string) => {
    if (!activeSessionId) {
      alert('请先选择或新建一个会话');
      return;
    }

    const targetSessionId = activeSessionId;
    const clientTurnId =
      existingTurnId || `turn-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;

    setPendingTurns((prev) => ({
      ...prev,
      [targetSessionId]: {
        sessionId: targetSessionId,
        clientTurnId,
        text,
        status: 'sending',
      },
    }));

    try {
      const res = await client.sendChat({
        session_id: targetSessionId,
        client_turn_id: clientTurnId,
        text,
      });

      // 仅当当前仍然停留在该会话时，才将消息和元数据贴入当前视图
      // (严格落实 C2: 切换会话时不要把旧请求结果贴进新会话)
      if (activeSessionIdRef.current === targetSessionId) {
        const nextIdx = messages.length + 1; // assistant message index
        setResponseMetaMap((meta) => ({
          ...meta,
          [nextIdx]: res,
        }));
        setMessages((prev) => [
          ...prev,
          { role: 'user', content: text },
          { role: 'assistant', content: res.reply },
        ]);

        // 更新数字人表情与情绪
        setCurrentExpression(res.expression);
        setCurrentEmotion(res.emotion);
        setCurrentModelVersion(res.model_version);
        setLastElapsedMs(res.elapsed_ms);
        setLastIsMock(res.is_mock);
      }

      // 成功完成，清除该会话的 pending 状态
      setPendingTurns((prev) => {
        const next = { ...prev };
        delete next[targetSessionId];
        return next;
      });

      // 刷新记忆（若有变动可能）
      loadMemories();
    } catch (err: unknown) {
      let errMsg = '发送失败，请稍后重试';
      if (err instanceof ApiError) {
        errMsg = `[${err.code}] ${err.message}`;
      } else if (err && typeof err === 'object' && 'error' in err) {
        errMsg = (err as any).error.message || errMsg;
      }
      setPendingTurns((prev) => ({
        ...prev,
        [targetSessionId]: {
          sessionId: targetSessionId,
          clientTurnId,
          text,
          status: 'failed',
          errorMessage: errMsg,
        },
      }));
    }
  };

  // 重试当前失败的轮次（严格保持 client_turn_id）
  const activePendingTurn = activeSessionId ? pendingTurns[activeSessionId] || null : null;

  const handleRetryPending = async () => {
    if (!activePendingTurn) return;
    await handleSendMessage(activePendingTurn.text, activePendingTurn.clientTurnId);
  };

  // 记忆操作
  const handleToggleMemoryEnabled = async (enabled: boolean) => {
    const res = await client.updateMemorySettings(enabled);
    setMemoryEnabled(res.enabled);
    setMemories(res.items);
  };

  const handleSaveMemory = async (key: MemoryKey, value: string) => {
    await client.saveMemory(key, value);
    await loadMemories();
  };

  const handleDeleteMemory = async (id: string) => {
    await client.deleteMemory(id);
    await loadMemories();
  };

  const handleClearMemories = async () => {
    await client.clearMemories();
    await loadMemories();
  };

  const activeSession = sessions.find((s) => s.id === activeSessionId);

  return (
    <div className="digital-person-app">
      <Header
        isMockMode={isMockMode}
        onToggleMockMode={handleToggleMockMode}
        health={health}
        healthError={healthError}
        onRefreshHealth={refreshHealth}
        simulate503={simulate503}
        onToggleSimulate503={handleToggle503}
        simulate409={simulate409}
        onToggleSimulate409={handleToggle409}
        onResetMockData={handleResetMockData}
      />

      <main className="app-main-layout">
        {/* 左侧：会话列表 */}
        <SessionList
          sessions={sessions}
          activeSessionId={activeSessionId}
          onSelectSession={setActiveSessionId}
          onCreateSession={handleCreateSession}
          onDeleteSession={handleDeleteSession}
        />

        {/* 中间：聊天主窗口 */}
        <div className="chat-center-container">
          <ChatWindow
            sessionTitle={activeSession?.title || '未选择会话'}
            messages={messages}
            latestResponseMeta={responseMetaMap}
            pendingTurn={activePendingTurn}
            onSendMessage={(t) => handleSendMessage(t)}
            onRetryPending={handleRetryPending}
            disabled={!activeSessionId}
          />
        </div>

        {/* 右侧：数字人与长期记忆面板 */}
        <aside className="right-sidebar">
          <AvatarDisplay
            expression={currentExpression}
            emotion={currentEmotion}
            modelVersion={currentModelVersion}
            elapsedMs={lastElapsedMs}
            isMock={lastIsMock || isMockMode}
            onSelectExpressionPreview={setCurrentExpression}
          />

          <MemoryPanel
            enabled={memoryEnabled}
            memories={memories}
            onToggleEnabled={handleToggleMemoryEnabled}
            onSaveMemory={handleSaveMemory}
            onDeleteMemory={handleDeleteMemory}
            onClearMemories={handleClearMemories}
          />
        </aside>
      </main>
    </div>
  );
};

export default App;
