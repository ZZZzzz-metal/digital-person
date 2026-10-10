import React, { useState } from 'react';
import { SessionDTO, formatBeijingTime } from '../api/types';

interface SessionListProps {
  sessions: SessionDTO[];
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onCreateSession: (title?: string) => Promise<void>;
  onDeleteSession: (id: string) => Promise<void>;
  loading?: boolean;
}

export const SessionList: React.FC<SessionListProps> = ({
  sessions,
  activeSessionId,
  onSelectSession,
  onCreateSession,
  onDeleteSession,
  loading = false,
}) => {
  const [newTitle, setNewTitle] = useState('');
  const [showInput, setShowInput] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setActionLoading(true);
    try {
      await onCreateSession(newTitle.trim() || undefined);
      setNewTitle('');
      setShowInput(false);
    } finally {
      setActionLoading(false);
    }
  };

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    if (!window.confirm('确定删除该会话吗？（提示：会话删除仅清除本轮聊天记录，长期事实记忆依然保留）')) {
      return;
    }
    setActionLoading(true);
    try {
      await onDeleteSession(id);
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <aside className="sidebar-sessions">
      <div className="sidebar-header">
        <h2 className="sidebar-title">对话会话</h2>
        <button
          type="button"
          className="btn-create-session"
          onClick={() => setShowInput((prev) => !prev)}
          disabled={loading || actionLoading}
        >
          {showInput ? '取消' : '+ 新建会话'}
        </button>
      </div>

      {showInput && (
        <form onSubmit={handleCreate} className="create-session-form">
          <input
            type="text"
            className="input-session-title"
            placeholder="会话主题（如：期末高数复习）"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            maxLength={100}
            autoFocus
          />
          <button type="submit" className="btn-confirm-create" disabled={actionLoading}>
            确定
          </button>
        </form>
      )}

      <div className="session-scroll-list">
        {sessions.length === 0 ? (
          <div className="empty-notice">暂无会话，点击上方新建</div>
        ) : (
          sessions.map((s) => {
            const isActive = s.id === activeSessionId;
            return (
              <div
                key={s.id}
                className={`session-item ${isActive ? 'active' : ''}`}
                onClick={() => onSelectSession(s.id)}
              >
                <div className="session-item-content">
                  <div className="session-title" title={s.title}>
                    {s.title}
                  </div>
                  <div className="session-date">{formatBeijingTime(s.created_at)}</div>
                </div>
                <button
                  type="button"
                  className="btn-delete-session"
                  title="删除此会话"
                  onClick={(e) => handleDelete(e, s.id)}
                >
                  ×
                </button>
              </div>
            );
          })
        )}
      </div>

      <div className="sidebar-footer-tip">
        提示：删除会话仅清理对话记录，长期事实记忆依然保留。
      </div>
    </aside>
  );
};
