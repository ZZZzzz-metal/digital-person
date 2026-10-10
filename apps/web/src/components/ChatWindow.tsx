import React, { useState, useRef, useEffect } from 'react';
import {
  Message,
  ChatResponse,
  EMOTION_LABELS,
  EXPRESSION_LABELS,
  MEMORY_KEY_LABELS,
} from '../api/types';

interface PendingTurn {
  clientTurnId: string;
  text: string;
  status: 'sending' | 'failed';
  errorMessage?: string;
}

interface ChatWindowProps {
  sessionTitle: string;
  messages: Message[];
  latestResponseMeta?: Record<number, ChatResponse>;
  pendingTurn: PendingTurn | null;
  onSendMessage: (text: string, turnId?: string) => Promise<void>;
  onRetryPending: () => Promise<void>;
  onDismissPending?: () => void;
  disabled?: boolean;
  isMockMode?: boolean;
}

const STARTER_PROMPTS = [
  '期末高数复习好焦虑，感觉知识点太多记不住...',
  '今天和室友产生了一点摩擦，心里有点堵...',
  '最近一直在准备英语六级，想制定个背单词计划！',
  '摄影比赛拿了一等奖，终于被大家认可了超级开心！',
];

export const ChatWindow: React.FC<ChatWindowProps> = ({
  sessionTitle,
  messages,
  latestResponseMeta = {},
  pendingTurn,
  onSendMessage,
  onRetryPending,
  onDismissPending,
  disabled = false,
  isMockMode = false,
}) => {
  const [inputText, setInputText] = useState('');
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const isSending = pendingTurn?.status === 'sending';
  const isFailed = pendingTurn?.status === 'failed';

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, pendingTurn]);

  const handleSelectPrompt = (prompt: string) => {
    setInputText(prompt);
    textareaRef.current?.focus();
  };

  const handleSend = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const clean = inputText.trim();
    if (!clean || clean.length > 2000 || isSending || disabled) {
      return;
    }
    setInputText('');
    await onSendMessage(clean);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex flex-col h-full bg-slate-50/50">
      {/* 顶部对话标题栏 */}
      <div className="h-14 shrink-0 border-b border-slate-200/80 bg-white/70 backdrop-blur-xs px-6 flex items-center justify-between">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-slate-900 truncate tracking-tight">
            {sessionTitle || '选择或新建会话'}
          </h3>
          <p className="text-[11px] text-slate-500 truncate">
            大学生日常情绪陪伴与备考倾诉 · 情感感知与记忆协同
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs text-slate-400">
          <span>{messages.length} 条对话</span>
        </div>
      </div>

      {/* 消息滚动流 */}
      <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-5">
        {messages.length === 0 && !pendingTurn && (
          <div className="mx-auto max-w-lg mt-8 text-center animate-[fade-in_.2s_ease-out]">
            <div className="mx-auto h-12 w-12 rounded-2xl bg-white border border-slate-200/80 shadow-xs flex items-center justify-center text-slate-600 mb-3">
              <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
                <path d="M12 21a9 9 0 1 0-9-9c0 1.48.36 2.88 1 4.12L3 21l4.88-1A8.96 8.96 0 0 0 12 21z" />
              </svg>
            </div>
            <h4 className="text-sm font-semibold text-slate-800">伴学数字人已就绪</h4>
            <p className="mt-1 text-xs text-slate-500 leading-relaxed">
              这里还没有消息。向伴学助手倾诉你的学习压力、宿舍烦恼、考试目标或开心日常吧～
            </p>

            {/* 快捷倾诉提示卡片 */}
            <div className="mt-6 flex flex-wrap justify-center gap-2">
              {STARTER_PROMPTS.map((prompt, pIdx) => (
                <button
                  key={pIdx}
                  type="button"
                  onClick={() => handleSelectPrompt(prompt)}
                  disabled={disabled}
                  className="rounded-full border border-slate-200 bg-white px-3.5 py-1.5 text-xs text-slate-600 shadow-xs hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900 active:scale-95 transition disabled:opacity-50"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, idx) => {
          const isUser = msg.role === 'user';
          const meta = !isUser ? latestResponseMeta[idx] : undefined;

          return (
            <div
              key={idx}
              className={`flex flex-col ${isUser ? 'items-end' : 'items-start'} animate-[fade-in_.15s_ease-out]`}
            >
              <div className="flex items-center gap-1.5 mb-1 text-[11px] font-medium text-slate-400">
                <span>{isUser ? '我' : '伴学助手'}</span>
              </div>

              {/* 消息气泡 */}
              <div
                className={`max-w-[85%] sm:max-w-[75%] rounded-2xl px-4 py-3 text-sm leading-relaxed shadow-xs whitespace-pre-wrap break-words ${
                  isUser
                    ? 'rounded-tr-xs bg-slate-900 text-white'
                    : 'rounded-tl-xs bg-white border border-slate-200/80 text-slate-800'
                }`}
              >
                <div>{msg.content}</div>

                {/* 伴学助手返回的元数据标签 */}
                {meta && (
                  <div className="mt-3 pt-2.5 border-t border-slate-100 flex flex-col gap-2">
                    <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                      {/* 表情标签 */}
                      <span className="rounded-md bg-sky-50 px-2 py-0.5 font-medium text-sky-700 border border-sky-100">
                        表情: {EXPRESSION_LABELS[meta.expression] || meta.expression}
                      </span>
                      {/* 情绪标签 */}
                      <span className="rounded-md bg-violet-50 px-2 py-0.5 font-medium text-violet-700 border border-violet-100">
                        情绪: {EMOTION_LABELS[meta.emotion] || meta.emotion}
                      </span>
                      {/* 耗时 */}
                      <span className="rounded-md bg-slate-50 px-1.5 py-0.5 font-mono text-slate-500 border border-slate-100">
                        {meta.elapsed_ms}ms
                      </span>
                      {/* 演示数据标识 */}
                      {meta.is_mock && (
                        <span className="rounded-md bg-amber-50 px-2 py-0.5 font-medium text-amber-700 border border-amber-200">
                          演示数据
                        </span>
                      )}
                    </div>

                    {/* 参考的事实记忆 */}
                    {meta.retrieved_memories && meta.retrieved_memories.length > 0 && (
                      <div className="rounded-lg bg-slate-50/80 p-2 border border-slate-100 text-xs text-slate-600">
                        <span className="text-[11px] font-medium text-slate-500 block mb-1">
                          📌 本轮参考记忆：
                        </span>
                        <div className="flex flex-wrap gap-1.5">
                          {meta.retrieved_memories.map((m, mIdx) => (
                            <span
                              key={mIdx}
                              className="rounded-md bg-white px-2 py-0.5 text-[11px] text-slate-700 border border-slate-200/70 shadow-xs"
                            >
                              <strong className="text-slate-900">{MEMORY_KEY_LABELS[m.key] || m.key}</strong>:{' '}
                              {m.value}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          );
        })}

        {/* 正在发送中的气泡 */}
        {pendingTurn && (
          <div className="flex flex-col items-end animate-[fade-in_.15s_ease-out]">
            <div className="flex items-center gap-1.5 mb-1 text-[11px] font-medium text-slate-400">
              <span>我</span>
            </div>
            <div
              className={`max-w-[85%] sm:max-w-[75%] rounded-2xl rounded-tr-xs px-4 py-3 text-sm leading-relaxed shadow-xs whitespace-pre-wrap break-words ${
                isFailed
                  ? 'bg-rose-50 border border-rose-300 text-rose-900'
                  : 'bg-slate-900 text-white'
              }`}
            >
              <div>{pendingTurn.text}</div>

              <div className="mt-2 pt-2 border-t border-white/20 text-xs">
                {isSending && (
                  <div className="flex items-center gap-2 text-slate-300">
                    <span className="inline-block h-2 w-2 rounded-full bg-slate-300 animate-ping" />
                    <span>模型思考与生成回复中…</span>
                  </div>
                )}
                {isFailed && (
                  <div className="flex flex-col gap-2 text-rose-700">
                    <span className="font-medium text-xs">
                      发送失败：{pendingTurn.errorMessage || '请求异常'}
                    </span>
                    <div className="flex items-center justify-end gap-2">
                      <button
                        type="button"
                        className="rounded-md border border-rose-300 bg-white px-2 py-1 text-xs text-rose-700 hover:bg-rose-50 active:scale-95 transition"
                        onClick={() => {
                          setInputText(pendingTurn.text);
                          textareaRef.current?.focus();
                        }}
                        title="将失败文本填入输入框"
                      >
                        编辑文本
                      </button>
                      {onDismissPending && (
                        <button
                          type="button"
                          className="rounded-md px-2 py-1 text-xs text-rose-600 hover:underline transition"
                          onClick={onDismissPending}
                          title="取消该轮未发送成功的消息"
                        >
                          取消
                        </button>
                      )}
                      <button
                        type="button"
                        className="rounded-md bg-rose-600 px-2.5 py-1 text-xs font-semibold text-white shadow-xs hover:bg-rose-700 active:scale-95 transition"
                        onClick={onRetryPending}
                        title="保留 client_turn_id 重试本轮发送"
                      >
                        重试
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* 底部输入框区域 */}
      <div className="border-t border-slate-200/80 bg-white/90 backdrop-blur-xs p-4">
        <form onSubmit={handleSend} className="max-w-4xl mx-auto space-y-2">
          <div className="relative rounded-2xl border border-slate-200 bg-white shadow-xs transition focus-within:border-slate-400 focus-within:ring-2 focus-within:ring-slate-900/10">
            <textarea
              ref={textareaRef}
              className="w-full resize-none bg-transparent p-3.5 pr-20 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none"
              placeholder={
                disabled
                  ? '请先在左侧选择或新建一个会话'
                  : '向伴学助手倾诉（回车发送，Shift + Enter 换行，最多 2000 字）...'
              }
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={disabled || isSending}
              rows={3}
              maxLength={2000}
            />
            {/* 字数统计 */}
            <div
              className={`absolute right-3 bottom-3 text-[11px] font-mono ${
                inputText.length > 1900 ? 'text-rose-600 font-bold' : 'text-slate-400'
              }`}
            >
              {inputText.length} / 2000
            </div>
          </div>

          <div className="flex items-center justify-between px-1">
            <span className="text-[11px] text-slate-400">
              {isMockMode
                ? '演示数据模式 (纯前端 Mock 剧本与情绪识别)'
                : '非流式单轮全响应 · 真实模型离线推理'}
            </span>
            <button
              type="submit"
              className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white shadow-xs hover:bg-slate-800 active:scale-95 transition disabled:opacity-40 disabled:pointer-events-none"
              disabled={disabled || isSending || !inputText.trim() || inputText.trim().length > 2000}
            >
              {isSending ? (
                <>
                  <svg className="h-4 w-4 animate-spin text-white" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                  </svg>
                  生成中…
                </>
              ) : (
                <>
                  <span>发送</span>
                  <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                    <line x1="22" y1="2" x2="11" y2="13" />
                    <polygon points="22 2 15 22 11 13 2 9 22 2" />
                  </svg>
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default ChatWindow;
