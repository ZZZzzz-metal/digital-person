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
  latestResponseMeta?: Record<number, ChatResponse>; // map assistant message index to response meta
  pendingTurn: PendingTurn | null;
  onSendMessage: (text: string, turnId?: string) => Promise<void>;
  onRetryPending: () => Promise<void>;
  disabled?: boolean;
}

export const ChatWindow: React.FC<ChatWindowProps> = ({
  sessionTitle,
  messages,
  latestResponseMeta = {},
  pendingTurn,
  onSendMessage,
  onRetryPending,
  disabled = false,
}) => {
  const [inputText, setInputText] = useState('');
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  const isSending = pendingTurn?.status === 'sending';
  const isFailed = pendingTurn?.status === 'failed';

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, pendingTurn]);

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
    <div className="chat-window-wrapper">
      <div className="chat-header">
        <h3 className="chat-session-title">{sessionTitle || '选择或新建会话'}</h3>
        <span className="chat-header-desc">大学生日常情绪陪伴与备考倾诉</span>
      </div>

      <div className="chat-messages-scroll">
        {messages.length === 0 && !pendingTurn && (
          <div className="chat-empty-state">
            <p>这里还没有消息。向伴学助手倾诉你的学习压力、宿舍烦恼或开心日常吧～</p>
          </div>
        )}

        {messages.map((msg, idx) => {
          const isUser = msg.role === 'user';
          const meta = !isUser ? latestResponseMeta[idx] : undefined;

          return (
            <div key={idx} className={`message-row ${isUser ? 'user-row' : 'assistant-row'}`}>
              <div className="bubble-wrapper">
                <div className="sender-name">{isUser ? '我' : '伴学助手'}</div>
                <div className={`message-bubble ${isUser ? 'user-bubble' : 'assistant-bubble'}`}>
                  <div className="message-text">{msg.content}</div>

                  {meta && (
                    <div className="message-meta-footer">
                      <div className="meta-tags-row">
                        <span className="meta-tag">
                          表情: {EXPRESSION_LABELS[meta.expression] || meta.expression}
                        </span>
                        <span className="meta-tag emotion-tag">
                          情绪估计: {EMOTION_LABELS[meta.emotion] || meta.emotion}
                        </span>
                        <span className="meta-tag time-tag">{meta.elapsed_ms}ms</span>
                        {meta.is_mock && <span className="meta-tag mock-tag">演示数据</span>}
                      </div>

                      {meta.retrieved_memories && meta.retrieved_memories.length > 0 && (
                        <div className="retrieved-memories-box">
                          <span className="retrieved-title">本轮参考记忆：</span>
                          <div className="retrieved-items">
                            {meta.retrieved_memories.map((m, mIdx) => (
                              <span key={mIdx} className="retrieved-item-pill">
                                <strong>{MEMORY_KEY_LABELS[m.key] || m.key}</strong>: {m.value}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        })}

        {/* 临时发送中/失败的用户气泡 */}
        {pendingTurn && (
          <div className="message-row user-row pending-row">
            <div className="bubble-wrapper">
              <div className="sender-name">我</div>
              <div className={`message-bubble user-bubble ${isFailed ? 'failed-bubble' : 'sending-bubble'}`}>
                <div className="message-text">{pendingTurn.text}</div>
                <div className="pending-status-row">
                  {isSending && <span className="status-sending">发送中，模型生成中...</span>}
                  {isFailed && (
                    <div className="status-failed">
                      <span>发送失败（{pendingTurn.errorMessage || '请求异常'}）</span>
                      <button
                        type="button"
                        className="btn-retry-turn"
                        onClick={onRetryPending}
                        title="使用相同 client_turn_id 重新发送"
                      >
                        重试
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <div className="chat-input-area">
        <form onSubmit={handleSend} className="input-form">
          <div className="textarea-container">
            <textarea
              className="chat-textarea"
              placeholder={disabled ? '请先选择或新建会话' : '输入倾诉内容，回车发送，Shift+Enter 换行（最多 2000 字）...'}
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={disabled || isSending}
              rows={3}
              maxLength={2000}
            />
            <div className="input-counter">
              {inputText.length} / 2000
            </div>
          </div>

          <div className="input-action-bar">
            <span className="input-hint">非流式交互 | 真实模型本地离线推理</span>
            <button
              type="submit"
              className="btn-send-message"
              disabled={disabled || isSending || !inputText.trim() || inputText.trim().length > 2000}
            >
              {isSending ? '生成中...' : '发送'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
