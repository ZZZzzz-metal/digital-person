import React, { useState } from 'react';
import { SessionDTO, formatBeijingTime } from '../api/types';
import ConfirmDialog from './ConfirmDialog';

interface SessionListProps {
  sessions: SessionDTO[];
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onCreateSession: (title?: string) => Promise<void>;
  onDeleteSession: (id: string) => Promise<void>;
  loading?: boolean;
  className?: string;
}

export const SessionList: React.FC<SessionListProps> = ({
  sessions,
  activeSessionId,
  onSelectSession,
  onCreateSession,
  onDeleteSession,
  loading = false,
  className = '',
}) => {
  const [newTitle, setNewTitle] = useState('');
  const [showInput, setShowInput] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(null);

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

  const handleConfirmDelete = async () => {
    if (!deletingSessionId) return;
    setActionLoading(true);
    try {
      await onDeleteSession(deletingSessionId);
      setDeletingSessionId(null);
    } finally {
      setActionLoading(false);
    }
  };

  const targetSessionToDelete = sessions.find((s) => s.id === deletingSessionId);

  return (
    <aside className={`w-72 shrink-0 border-r border-slate-200/80 bg-white/70 backdrop-blur-xs flex flex-col h-full ${className}`}>
      {/* 头部 */}
      <div className="p-4 border-b border-slate-200/60 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-slate-900 tracking-tight">对话会话</h2>
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600">
            {sessions.length}
          </span>
        </div>
        <button
          type="button"
          className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 shadow-xs hover:bg-slate-50 hover:text-slate-900 active:scale-95 transition disabled:opacity-50"
          onClick={() => setShowInput((prev) => !prev)}
          disabled={loading || actionLoading}
        >
          {showInput ? (
            '取消'
          ) : (
            <>
              <svg className="h-3.5 w-3.5 text-slate-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                <line x1="12" y1="5" x2="12" y2="19" />
                <line x1="5" y1="12" x2="19" y2="12" />
              </svg>
              新建会话
            </>
          )}
        </button>
      </div>

      {/* 新建会话表单（展开时） */}
      {showInput && (
        <form onSubmit={handleCreate} className="p-3 bg-slate-50 border-b border-slate-200/80 animate-[fade-in_.15s_ease-out]">
          <input
            type="text"
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-900 shadow-xs placeholder:text-slate-400 focus:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-900/10"
            placeholder="输入主题，如：高数备考倾诉"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                setShowInput(false);
                setNewTitle('');
              }
            }}
            maxLength={100}
            autoFocus
          />
          <div className="mt-2 flex justify-end gap-1.5">
            <button
              type="button"
              className="rounded-md px-2 py-1 text-xs text-slate-500 hover:text-slate-700"
              onClick={() => {
                setShowInput(false);
                setNewTitle('');
              }}
            >
              取消
            </button>
            <button
              type="submit"
              className="rounded-md bg-slate-900 px-3 py-1 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50"
              disabled={actionLoading}
            >
              {actionLoading ? '创建中…' : '确认创建'}
            </button>
          </div>
        </form>
      )}

      {/* 会话列表 */}
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {sessions.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
            <div className="h-10 w-10 rounded-full bg-slate-100 flex items-center justify-center text-slate-400 mb-2">
              <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75}>
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </svg>
            </div>
            <p className="text-xs text-slate-500">暂无会话</p>
            <p className="text-[11px] text-slate-400 mt-1">点击右上角「新建会话」开始交流</p>
          </div>
        ) : (
          sessions.map((s) => {
            const isActive = s.id === activeSessionId;
            return (
              <div
                key={s.id}
                onClick={() => onSelectSession(s.id)}
                className={`group relative flex items-center justify-between rounded-xl p-3 cursor-pointer transition text-left ${
                  isActive
                    ? 'bg-slate-100 text-slate-900 font-medium shadow-xs border-l-[3px] border-slate-900'
                    : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'
                }`}
              >
                <div className="min-w-0 flex-1 pr-2">
                  <div className="text-xs font-medium truncate" title={s.title}>
                    {s.title}
                  </div>
                  <div className="mt-1 flex items-center gap-1 text-[11px] text-slate-400">
                    <svg className="h-3 w-3 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}>
                      <circle cx="12" cy="12" r="10" />
                      <polyline points="12 6 12 12 16 14" />
                    </svg>
                    <span>{formatBeijingTime(s.created_at)}</span>
                  </div>
                </div>

                {/* 删除按钮 */}
                <button
                  type="button"
                  className="opacity-0 group-hover:opacity-100 focus:opacity-100 rounded-md p-1 text-slate-400 hover:bg-rose-50 hover:text-rose-600 transition"
                  title="删除此会话"
                  onClick={(e) => {
                    e.stopPropagation();
                    setDeletingSessionId(s.id);
                  }}
                >
                  <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                    <line x1="18" y1="6" x2="6" y2="18" />
                    <line x1="6" y1="6" x2="18" y2="18" />
                  </svg>
                </button>
              </div>
            );
          })
        )}
      </div>

      {/* 底部提示卡片 */}
      <div className="p-3 border-t border-slate-200/60 bg-slate-50/50">
        <p className="text-[11px] leading-relaxed text-slate-400">
          💡 <strong>独立存储提示</strong>：删除会话仅清理对话记录，长期事实记忆依然安全保留。
        </p>
      </div>

      {/* 删除会话确认弹窗 */}
      <ConfirmDialog
        open={Boolean(deletingSessionId)}
        title="确认删除该会话？"
        confirmText="确认删除"
        danger
        busy={actionLoading}
        onConfirm={handleConfirmDelete}
        onCancel={() => setDeletingSessionId(null)}
      >
        <p>
          将删除会话「{targetSessionToDelete?.title || '当前会话'}」的所有聊天记录。
        </p>
        <p className="mt-1 text-xs text-slate-500">
          注意：此操作不会清除您已保存的长期事实记忆。
        </p>
      </ConfirmDialog>
    </aside>
  );
};

export default SessionList;
