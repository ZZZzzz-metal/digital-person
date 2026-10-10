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
  MEMORY_KEY_LABELS,
} from './api/types';
import { ApiClient, ApiError } from './api/client';
import { mockEngine } from './api/mock';
import { Header } from './components/Header';
import { ModeBanner } from './components/ModeBanner';
import { AvatarDisplay } from './components/AvatarDisplay';
import { SessionList } from './components/SessionList';
import { ChatWindow } from './components/ChatWindow';
import { MemoryPanel } from './components/MemoryPanel';
import { ToastProvider, useToast } from './components/Toast';
import ConfirmDialog from './components/ConfirmDialog';

interface PendingTurn {
  sessionId: string;
  clientTurnId: string;
  text: string;
  status: 'sending' | 'failed';
  errorMessage?: string;
}

export type MobileTab = 'chat' | 'sessions' | 'avatar' | 'memories';

const DigitalPersonApp: React.FC = () => {
  const toast = useToast();
  const clientRef = useRef<ApiClient>(new ApiClient());
  const client = clientRef.current;

  const [isMockMode, setIsMockMode] = useState<boolean>(client.isMock());
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [healthRefreshing, setHealthRefreshing] = useState<boolean>(false);

  // 移动端/平板选中的 Tab 视窗
  const [mobileTab, setMobileTab] = useState<MobileTab>('chat');

  // 会话与消息状态
  const [sessions, setSessions] = useState<SessionDTO[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const activeSessionIdRef = useRef<string | null>(null);
  activeSessionIdRef.current = activeSessionId;

  const [messages, setMessages] = useState<Message[]>([]);
  const [responseMetaMap, setResponseMetaMap] = useState<Record<number, ChatResponse>>({});

  // 发送中/失败状态：按 session_id 隔离
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
  const [showResetConfirm, setShowResetConfirm] = useState<boolean>(false);

  // 1. 获取健康状态
  const refreshHealth = useCallback(async () => {
    setHealthRefreshing(true);
    try {
      const h = await client.getHealth();
      setHealth(h);
      setHealthError(null);
      setCurrentModelVersion(h.model_version);
      setLastIsMock(h.is_mock);
    } catch (err: unknown) {
      setHealth(null);
      const msg = err instanceof Error ? err.message : '连接后端失败';
      setHealthError(msg);
    } finally {
      setHealthRefreshing(false);
    }
  }, [client]);

  // 2. 加载会话列表
  const loadSessions = useCallback(async () => {
    try {
      const list = await client.listSessions();
      setSessions(list);
      if (list.length > 0 && !activeSessionIdRef.current) {
        setActiveSessionId(list[0].id);
      }
    } catch (err: unknown) {
      console.error('加载会话失败:', err);
      toast('加载会话列表失败', 'error');
    }
  }, [client, toast]);

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
    toast(
      mock
        ? '已切换至纯前端本地 Mock 模式（离线运行）'
        : '已切换至真实后端模式 (FastAPI)',
      'info'
    );
  };

  // 重置 Mock 演示数据
  const handleResetMockData = () => {
    mockEngine.resetToDefault();
    setSimulate503(false);
    setSimulate409(false);
    setShowResetConfirm(false);
    refreshHealth();
    loadSessions();
    loadMemories();
    toast('已重置演示数据为初始剧本状态', 'success');
  };

  const handleToggle503 = () => {
    mockEngine.simulate503 = !simulate503;
    const nextVal = !simulate503;
    setSimulate503(nextVal);
    refreshHealth();
    toast(nextVal ? '已开启 503 故障模拟' : '已取消 503 故障模拟', 'info');
  };

  const handleToggle409 = () => {
    mockEngine.simulate409 = !simulate409;
    const nextVal = !simulate409;
    setSimulate409(nextVal);
    toast(nextVal ? '已开启 409 冲突模拟' : '已取消 409 冲突模拟', 'info');
  };

  // 会话操作
  const handleCreateSession = async (title?: string) => {
    try {
      const s = await client.createSession(title);
      setSessions((prev) => [s, ...prev]);
      setActiveSessionId(s.id);
      toast(`已新建会话「${s.title}」`, 'success');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '创建会话失败';
      toast(msg, 'error');
    }
  };

  const handleDeleteSession = async (id: string) => {
    try {
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
      toast('会话已删除', 'info');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '删除会话失败';
      toast(msg, 'error');
    }
  };

  // 发送消息
  const handleSendMessage = async (text: string, existingTurnId?: string) => {
    if (!activeSessionId) {
      toast('请先在左侧选择或新建一个会话', 'error');
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
      if (activeSessionIdRef.current === targetSessionId) {
        const nextIdx = messages.length + 1;
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

      // 清除该会话的 pending 状态
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
      toast(`发送失败: ${errMsg}`, 'error');
    }
  };

  // 重试当前失败的轮次
  const activePendingTurn = activeSessionId ? pendingTurns[activeSessionId] || null : null;

  const handleRetryPending = async () => {
    if (!activePendingTurn) return;
    await handleSendMessage(activePendingTurn.text, activePendingTurn.clientTurnId);
  };

  const handleDismissPending = () => {
    if (!activeSessionId) return;
    setPendingTurns((prev) => {
      const next = { ...prev };
      delete next[activeSessionId];
      return next;
    });
  };

  // 记忆操作
  const handleToggleMemoryEnabled = async (enabled: boolean) => {
    try {
      const res = await client.updateMemorySettings(enabled);
      setMemoryEnabled(res.enabled);
      setMemories(res.items);
      toast(enabled ? '长期事实记忆已开启' : '长期事实记忆已关闭', 'info');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '更新记忆状态失败';
      toast(msg, 'error');
    }
  };

  const handleSaveMemory = async (key: MemoryKey, value: string) => {
    try {
      await client.saveMemory(key, value);
      await loadMemories();
      toast(`已更新${MEMORY_KEY_LABELS[key]}记忆`, 'success');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '保存记忆失败';
      toast(msg, 'error');
      throw err;
    }
  };

  const handleDeleteMemory = async (id: string) => {
    try {
      await client.deleteMemory(id);
      await loadMemories();
      toast('记忆已删除', 'info');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '删除记忆失败';
      toast(msg, 'error');
      throw err;
    }
  };

  const handleClearMemories = async () => {
    try {
      await client.clearMemories();
      await loadMemories();
      toast('所有长期事实记忆已清空', 'info');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '清空记忆失败';
      toast(msg, 'error');
      throw err;
    }
  };

  const activeSession = sessions.find((s) => s.id === activeSessionId);

  const handleSelectSession = (id: string) => {
    setActiveSessionId(id);
    setMobileTab('chat');
  };

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-slate-50 text-slate-800">
      {/* 顶部导航栏 */}
      <Header
        isMockMode={isMockMode}
        onToggleMockMode={handleToggleMockMode}
        health={health}
        healthError={healthError}
        memoryEnabled={memoryEnabled}
        onRefreshHealth={refreshHealth}
        simulate503={simulate503}
        onToggleSimulate503={handleToggle503}
        simulate409={simulate409}
        onToggleSimulate409={handleToggle409}
        onResetMockData={() => setShowResetConfirm(true)}
        healthRefreshing={healthRefreshing}
      />

      {/* 模式与状态全局提示条（对齐 AIClassRep ConnectBanner 规范） */}
      <ModeBanner
        isMockMode={isMockMode}
        onToggleMockMode={handleToggleMockMode}
        health={health}
        healthError={healthError}
        onResetMockData={() => setShowResetConfirm(true)}
        onRefreshHealth={refreshHealth}
      />

      {/* 主工作区：桌面端三列流式协同 / 移动端与平板自适应单页视窗 */}
      <main className="flex flex-1 overflow-hidden relative">
        {/* === 桌面端 (lg 及以上)：高品质经典三列架构 === */}
        <div className="hidden lg:flex flex-1 h-full overflow-hidden">
          {/* 左列：会话列表 */}
          <SessionList
            sessions={sessions}
            activeSessionId={activeSessionId}
            onSelectSession={setActiveSessionId}
            onCreateSession={handleCreateSession}
            onDeleteSession={handleDeleteSession}
          />

          {/* 中列：聊天视窗 */}
          <div className="flex-1 min-w-0 h-full overflow-hidden">
            <ChatWindow
              sessionTitle={activeSession?.title || '未选择会话'}
              messages={messages}
              latestResponseMeta={responseMetaMap}
              pendingTurn={activePendingTurn}
              onSendMessage={(t) => handleSendMessage(t)}
              onRetryPending={handleRetryPending}
              onDismissPending={handleDismissPending}
              disabled={!activeSessionId}
              isMockMode={isMockMode}
            />
          </div>

          {/* 右列：数字人状态与记忆管理侧栏 */}
          <aside className="w-96 shrink-0 border-l border-slate-200/80 bg-slate-50/60 overflow-y-auto p-4 space-y-4">
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
        </div>

        {/* === 移动端与平板 (< lg)：自适应 Tab 视窗 === */}
        <div className="flex lg:hidden flex-1 h-full overflow-hidden">
          {mobileTab === 'chat' && (
            <div className="flex-1 min-w-0 h-full pb-16 overflow-hidden">
              <ChatWindow
                sessionTitle={activeSession?.title || '未选择会话'}
                messages={messages}
                latestResponseMeta={responseMetaMap}
                pendingTurn={activePendingTurn}
                onSendMessage={(t) => handleSendMessage(t)}
                onRetryPending={handleRetryPending}
                onDismissPending={handleDismissPending}
                disabled={!activeSessionId}
                isMockMode={isMockMode}
              />
            </div>
          )}

          {mobileTab === 'sessions' && (
            <div className="flex-1 h-full pb-16 overflow-hidden">
              <SessionList
                sessions={sessions}
                activeSessionId={activeSessionId}
                onSelectSession={handleSelectSession}
                onCreateSession={handleCreateSession}
                onDeleteSession={handleDeleteSession}
                className="w-full border-r-0"
              />
            </div>
          )}

          {mobileTab === 'avatar' && (
            <div className="flex-1 h-full pb-16 overflow-y-auto p-4">
              <AvatarDisplay
                expression={currentExpression}
                emotion={currentEmotion}
                modelVersion={currentModelVersion}
                elapsedMs={lastElapsedMs}
                isMock={lastIsMock || isMockMode}
                onSelectExpressionPreview={setCurrentExpression}
                className="max-w-md mx-auto"
              />
            </div>
          )}

          {mobileTab === 'memories' && (
            <div className="flex-1 h-full pb-16 overflow-y-auto p-4">
              <MemoryPanel
                enabled={memoryEnabled}
                memories={memories}
                onToggleEnabled={handleToggleMemoryEnabled}
                onSaveMemory={handleSaveMemory}
                onDeleteMemory={handleDeleteMemory}
                onClearMemories={handleClearMemories}
                className="max-w-md mx-auto"
              />
            </div>
          )}
        </div>
      </main>

      {/* 移动端与平板底部导航栏（对齐 AIClassRep Layout 规范） */}
      <nav className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 border-t border-slate-200/80 bg-white/95 backdrop-blur-md pb-[env(safe-area-inset-bottom)] lg:hidden shadow-xs">
        <button
          type="button"
          onClick={() => setMobileTab('chat')}
          className={`flex flex-col items-center gap-0.5 py-2 text-[11px] font-medium transition ${
            mobileTab === 'chat' ? 'text-slate-900 font-semibold' : 'text-slate-400 hover:text-slate-600'
          }`}
        >
          <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
          <span>对话</span>
        </button>

        <button
          type="button"
          onClick={() => setMobileTab('sessions')}
          className={`flex flex-col items-center gap-0.5 py-2 text-[11px] font-medium transition ${
            mobileTab === 'sessions' ? 'text-slate-900 font-semibold' : 'text-slate-400 hover:text-slate-600'
          }`}
        >
          <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
            <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
            <circle cx="9" cy="7" r="4" />
            <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
            <path d="M16 3.13a4 4 0 0 1 0 7.75" />
          </svg>
          <span>会话 ({sessions.length})</span>
        </button>

        <button
          type="button"
          onClick={() => setMobileTab('avatar')}
          className={`flex flex-col items-center gap-0.5 py-2 text-[11px] font-medium transition ${
            mobileTab === 'avatar' ? 'text-slate-900 font-semibold' : 'text-slate-400 hover:text-slate-600'
          }`}
        >
          <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
            <circle cx="12" cy="12" r="10" />
            <path d="M8 14s1.5 2 4 2 4-2 4-2" />
            <line x1="9" y1="9" x2="9.01" y2="9" />
            <line x1="15" y1="9" x2="15.01" y2="9" />
          </svg>
          <span>数字人</span>
        </button>

        <button
          type="button"
          onClick={() => setMobileTab('memories')}
          className={`flex flex-col items-center gap-0.5 py-2 text-[11px] font-medium transition ${
            mobileTab === 'memories' ? 'text-slate-900 font-semibold' : 'text-slate-400 hover:text-slate-600'
          }`}
        >
          <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
            <path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
          </svg>
          <span>记忆 ({memoryEnabled ? memories.length : '关'})</span>
        </button>
      </nav>

      {/* 重置演示数据确认弹窗 */}
      <ConfirmDialog
        open={showResetConfirm}
        title="确认重置演示数据？"
        confirmText="确认重置"
        danger
        onConfirm={handleResetMockData}
        onCancel={() => setShowResetConfirm(false)}
      >
        <p>将恢复纯前端 Mock 数据库中的初始预置剧本、会话和长期事实记忆。</p>
      </ConfirmDialog>
    </div>
  );
};

export const App: React.FC = () => {
  return (
    <ToastProvider>
      <DigitalPersonApp />
    </ToastProvider>
  );
};

export default App;
