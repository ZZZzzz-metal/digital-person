import React, { useState, useRef } from 'react';
import {
  MemoryItem,
  MemoryKey,
  MEMORY_KEY_LABELS,
  formatBeijingTime,
} from '../api/types';
import ConfirmDialog from './ConfirmDialog';

interface MemoryPanelProps {
  enabled: boolean;
  memories: MemoryItem[];
  onToggleEnabled: (enabled: boolean) => Promise<void>;
  onSaveMemory: (key: MemoryKey, value: string) => Promise<void>;
  onDeleteMemory: (id: string) => Promise<void>;
  onClearMemories: () => Promise<void>;
  loading?: boolean;
  className?: string;
}

const ALL_KEYS: MemoryKey[] = [
  'preferred_name',
  'study_goal',
  'exam_subject',
  'response_preference',
  'hobby',
];

export const KEY_PLACEHOLDERS: Record<MemoryKey, string> = {
  preferred_name: '如：小航、同学、学长',
  study_goal: '如：每天背50个单词、冲刺六级550分、期末GPA 3.8',
  exam_subject: '如：高等数学、线性代数、计算机系统结构',
  response_preference: '如：温和鼓励、逻辑清晰条理分明、言简意赅',
  hobby: '如：数码摄影、篮球运动、民谣吉他、科幻小说',
};

export const MemoryPanel: React.FC<MemoryPanelProps> = ({
  enabled,
  memories,
  onToggleEnabled,
  onSaveMemory,
  onDeleteMemory,
  onClearMemories,
  loading = false,
  className = '',
}) => {
  const [selectedKey, setSelectedKey] = useState<MemoryKey>('exam_subject');
  const [inputValue, setInputValue] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  // 弹窗状态
  const [showClearConfirm, setShowClearConfirm] = useState(false);
  const [deletingMemoryId, setDeletingMemoryId] = useState<string | null>(null);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);
    const clean = inputValue.trim();
    if (!clean) {
      setErrorMsg('记忆内容不能为空');
      return;
    }
    if (clean.length > 200) {
      setErrorMsg('记忆内容最多不超过 200 字符');
      return;
    }

    setSaving(true);
    try {
      await onSaveMemory(selectedKey, clean);
      setInputValue('');
      setEditingId(null);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '保存记忆失败';
      setErrorMsg(msg);
    } finally {
      setSaving(false);
    }
  };

  const handleEditClick = (item: MemoryItem) => {
    setSelectedKey(item.key);
    setInputValue(item.value);
    setEditingId(item.id);
    setErrorMsg(null);
    inputRef.current?.focus();
  };

  const handleCancelEdit = () => {
    setInputValue('');
    setEditingId(null);
    setErrorMsg(null);
  };

  const handleConfirmClearAll = async () => {
    setSaving(true);
    try {
      await onClearMemories();
      setShowClearConfirm(false);
    } finally {
      setSaving(false);
    }
  };

  const handleConfirmDeleteSingle = async () => {
    if (!deletingMemoryId) return;
    setSaving(true);
    try {
      await onDeleteMemory(deletingMemoryId);
      setDeletingMemoryId(null);
    } finally {
      setSaving(false);
    }
  };

  const targetMemoryToDelete = memories.find((m) => m.id === deletingMemoryId);

  return (
    <div className={`rounded-2xl border border-slate-200/80 bg-white p-5 shadow-xs transition hover:shadow-sm ${className}`}>
      {/* 头部标题与记忆启闭开关 */}
      <div className="flex items-center justify-between pb-3 border-b border-slate-100">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-slate-900 tracking-tight">长期事实记忆</h3>
          <span className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">
            用户级持久化
          </span>
        </div>

        {/* 现代风格滑动开关 */}
        <label className="relative inline-flex items-center cursor-pointer">
          <input
            type="checkbox"
            className="sr-only peer"
            checked={enabled}
            onChange={(e) => onToggleEnabled(e.target.checked)}
            disabled={loading || saving}
          />
          <div className="w-9 h-5 bg-slate-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-slate-900" />
          <span className="ml-2 text-xs font-medium text-slate-600">
            {enabled ? '开启' : '关闭'}
          </span>
        </label>
      </div>

      {/* 记忆停用时的提示条 */}
      {!enabled && (
        <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs leading-relaxed text-amber-900 animate-[fade-in_.15s_ease-out]">
          <strong>记忆功能已关闭</strong>：已有事实安全保留在库中，但在对话中不会检索或引用，亦不可保存新记忆。重新开启后即可恢复使用。
        </div>
      )}

      {/* 录入与纠正表单（开启时） */}
      {enabled && (
        <form onSubmit={handleSave} className="mt-4 space-y-2.5 animate-[fade-in_.15s_ease-out]">
          {editingId && (
            <div className="flex items-center justify-between rounded-lg bg-sky-50 border border-sky-200 px-2.5 py-1.5 text-xs text-sky-800">
              <span className="truncate">
                ✏️ 正在纠正「{MEMORY_KEY_LABELS[selectedKey]}」事实（保存后保留同一 ID）
              </span>
              <button
                type="button"
                className="text-[11px] font-medium text-sky-700 hover:text-sky-900 underline ml-2 shrink-0"
                onClick={handleCancelEdit}
              >
                取消纠正
              </button>
            </div>
          )}

          <div>
            <label className="block text-[11px] font-medium text-slate-500 mb-1">
              事实类型 (5 种白名单键)：
            </label>
            <select
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-800 shadow-xs focus:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-900/10"
              value={selectedKey}
              onChange={(e) => {
                setSelectedKey(e.target.value as MemoryKey);
                setErrorMsg(null);
              }}
              disabled={loading || saving}
            >
              {ALL_KEYS.map((k) => (
                <option key={k} value={k}>
                  {MEMORY_KEY_LABELS[k]} ({k})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-[11px] font-medium text-slate-500 mb-1">
              {editingId ? '纠正后内容：' : '事实内容 (输入后保存)：'}
            </label>
            <input
              ref={inputRef}
              type="text"
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-900 shadow-xs placeholder:text-slate-400 focus:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-900/10"
              placeholder={KEY_PLACEHOLDERS[selectedKey] || `输入${MEMORY_KEY_LABELS[selectedKey]}`}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              maxLength={200}
              disabled={loading || saving}
            />
          </div>

          {errorMsg && (
            <p className="text-xs text-rose-600 font-medium">{errorMsg}</p>
          )}

          <div className="flex justify-end gap-2 pt-1">
            {editingId && (
              <button
                type="button"
                className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 active:scale-95 transition"
                onClick={handleCancelEdit}
                disabled={saving}
              >
                取消
              </button>
            )}
            <button
              type="submit"
              className="rounded-lg bg-slate-900 px-3.5 py-1.5 text-xs font-medium text-white shadow-xs hover:bg-slate-800 active:scale-95 transition disabled:opacity-40"
              disabled={loading || saving || !inputValue.trim()}
            >
              {saving
                ? '保存中…'
                : editingId
                ? '确认纠正记忆'
                : '确认保存新记忆'}
            </button>
          </div>
        </form>
      )}

      {/* 已存事实列表 */}
      <div className="mt-4 pt-3 border-t border-slate-100">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-medium text-slate-700">
            已存事实列表 ({enabled ? memories.length : 0})
          </span>
          {enabled && memories.length > 0 && (
            <button
              type="button"
              className="text-xs text-rose-600 hover:text-rose-800 hover:underline transition"
              onClick={() => setShowClearConfirm(true)}
              disabled={loading || saving}
            >
              清空全部
            </button>
          )}
        </div>

        {memories.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-200 p-4 text-center text-xs text-slate-400">
            {enabled ? '暂无事实记忆，可在上方录入' : '记忆已关闭'}
          </div>
        ) : (
          <div className="max-h-60 overflow-y-auto space-y-2 pr-1">
            {memories.map((m) => (
              <div
                key={m.id}
                className="group rounded-xl border border-slate-200/80 bg-slate-50/50 p-2.5 transition hover:border-slate-300 hover:bg-white shadow-xs"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="rounded-md bg-violet-50 px-2 py-0.5 text-[11px] font-semibold text-violet-700 border border-violet-100">
                    {MEMORY_KEY_LABELS[m.key] || m.key}
                  </span>
                  <span className="text-[10px] text-slate-400">
                    {formatBeijingTime(m.updated_at)}
                  </span>
                </div>

                <div className="mt-1.5 text-xs font-medium text-slate-800 break-words">
                  {m.value}
                </div>

                <div className="mt-2 flex items-center justify-end gap-2 pt-1 border-t border-slate-100/80">
                  <button
                    type="button"
                    className="text-[11px] font-medium text-slate-600 hover:text-slate-900 transition"
                    onClick={() => handleEditClick(m)}
                    disabled={!enabled || loading || saving}
                  >
                    修改纠正
                  </button>
                  <button
                    type="button"
                    className="text-[11px] font-medium text-rose-600 hover:text-rose-700 transition"
                    onClick={() => setDeletingMemoryId(m.id)}
                    disabled={loading || saving}
                  >
                    删除
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 规则机制说明小注 */}
      <div className="mt-4 rounded-xl bg-slate-50 p-3 text-[11px] leading-relaxed text-slate-500 border border-slate-100">
        <strong className="text-slate-700 block mb-1">长期记忆机制说明：</strong>
        <ul className="list-disc pl-3.5 space-y-0.5 text-slate-500">
          <li>仅保存用户确认的事实，不自动将情绪推测持久化；</li>
          <li>同类事实更新值即可完成记忆纠正；</li>
          <li>关闭记忆不等于清空已有数据；</li>
          <li>会话删除不影响长期记忆。</li>
        </ul>
      </div>

      {/* 清空记忆确认弹窗 */}
      <ConfirmDialog
        open={showClearConfirm}
        title="确定清空全部长期记忆？"
        confirmText="清空记忆"
        danger
        focusCancel
        busy={saving}
        onConfirm={handleConfirmClearAll}
        onCancel={() => setShowClearConfirm(false)}
      >
        <p>
          此操作将删除当前用户的全部事实记忆（称呼、考试科目、目标等），此操作不可撤销。
        </p>
      </ConfirmDialog>

      {/* 单条记忆删除确认弹窗 */}
      <ConfirmDialog
        open={Boolean(deletingMemoryId)}
        title="确认删除该条记忆？"
        confirmText="删除"
        danger
        busy={saving}
        onConfirm={handleConfirmDeleteSingle}
        onCancel={() => setDeletingMemoryId(null)}
      >
        <p>
          确认删除记忆「{targetMemoryToDelete ? MEMORY_KEY_LABELS[targetMemoryToDelete.key] : ''}：{targetMemoryToDelete?.value}」吗？
        </p>
      </ConfirmDialog>
    </div>
  );
};

export default MemoryPanel;
