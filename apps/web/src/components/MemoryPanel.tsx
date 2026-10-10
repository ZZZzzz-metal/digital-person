import React, { useState } from 'react';
import {
  MemoryItem,
  MemoryKey,
  MEMORY_KEY_LABELS,
  formatBeijingTime,
} from '../api/types';

interface MemoryPanelProps {
  enabled: boolean;
  memories: MemoryItem[];
  onToggleEnabled: (enabled: boolean) => Promise<void>;
  onSaveMemory: (key: MemoryKey, value: string) => Promise<void>;
  onDeleteMemory: (id: string) => Promise<void>;
  onClearMemories: () => Promise<void>;
  loading?: boolean;
}

const ALL_KEYS: MemoryKey[] = [
  'preferred_name',
  'study_goal',
  'exam_subject',
  'response_preference',
  'hobby',
];

export const MemoryPanel: React.FC<MemoryPanelProps> = ({
  enabled,
  memories,
  onToggleEnabled,
  onSaveMemory,
  onDeleteMemory,
  onClearMemories,
  loading = false,
}) => {
  const [selectedKey, setSelectedKey] = useState<MemoryKey>('exam_subject');
  const [inputValue, setInputValue] = useState('');
  const [saving, setSaving] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

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
    } catch (err: any) {
      setErrorMsg(err.message || '保存记忆失败');
    } finally {
      setSaving(false);
    }
  };

  const handleEditClick = (item: MemoryItem) => {
    setSelectedKey(item.key);
    setInputValue(item.value);
    setErrorMsg(null);
  };

  const handleClearAll = async () => {
    if (window.confirm('警告：确定清空当前用户的全部长期记忆吗？此操作不可撤销。')) {
      setSaving(true);
      try {
        await onClearMemories();
      } finally {
        setSaving(false);
      }
    }
  };

  return (
    <div className="memory-panel-wrapper">
      <div className="memory-header">
        <div className="memory-title-group">
          <h3 className="memory-title">长期事实记忆</h3>
          <span className="memory-scope-tag">用户级持久化</span>
        </div>
        <div className="memory-toggle-container">
          <label className="switch-label">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => onToggleEnabled(e.target.checked)}
              disabled={loading || saving}
            />
            <span className="switch-text">{enabled ? '记忆开启' : '记忆关闭'}</span>
          </label>
        </div>
      </div>

      {!enabled && (
        <div className="memory-disabled-notice">
          <strong>记忆功能已关闭</strong>：已有事实保留在库中，但对话中不会检索或引用，亦不可保存新记忆。
        </div>
      )}

      {enabled && (
        <form onSubmit={handleSave} className="memory-form">
          <div className="form-row">
            <label className="field-label">事实类型：</label>
            <select
              className="select-memory-key"
              value={selectedKey}
              onChange={(e) => setSelectedKey(e.target.value as MemoryKey)}
              disabled={loading || saving}
            >
              {ALL_KEYS.map((k) => (
                <option key={k} value={k}>
                  {MEMORY_KEY_LABELS[k]} ({k})
                </option>
              ))}
            </select>
          </div>

          <div className="form-row">
            <label className="field-label">确认内容：</label>
            <input
              type="text"
              className="input-memory-val"
              placeholder={`输入${MEMORY_KEY_LABELS[selectedKey]}（如：高等数学、小航）`}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              maxLength={200}
              disabled={loading || saving}
            />
          </div>

          {errorMsg && <div className="form-error-text">{errorMsg}</div>}

          <div className="form-actions">
            <button
              type="submit"
              className="btn-save-memory"
              disabled={loading || saving || !inputValue.trim()}
            >
              {saving ? '保存中...' : '确认保存/纠正记忆'}
            </button>
          </div>
        </form>
      )}

      <div className="memory-list-container">
        <div className="memory-list-header">
          <span>当前保存事实 ({enabled ? memories.length : 0})</span>
          {memories.length > 0 && (
            <button
              type="button"
              className="btn-clear-all"
              onClick={handleClearAll}
              disabled={loading || saving}
            >
              清空记忆
            </button>
          )}
        </div>

        {memories.length === 0 ? (
          <div className="empty-memories-text">
            {enabled ? '暂无确认的事实记忆，请在上方添加' : '记忆已关闭'}
          </div>
        ) : (
          <div className="memory-cards-scroll">
            {memories.map((m) => (
              <div key={m.id} className="memory-item-card">
                <div className="memory-card-header">
                  <span className="memory-key-tag">{MEMORY_KEY_LABELS[m.key] || m.key}</span>
                  <span className="memory-time">{formatBeijingTime(m.updated_at)}</span>
                </div>
                <div className="memory-value-text">{m.value}</div>
                <div className="memory-item-actions">
                  <button
                    type="button"
                    className="btn-action-small"
                    onClick={() => handleEditClick(m)}
                    disabled={!enabled || loading || saving}
                  >
                    修改
                  </button>
                  <button
                    type="button"
                    className="btn-action-small btn-delete"
                    onClick={() => onDeleteMemory(m.id)}
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

      <div className="memory-disclaimer-box">
        <p><strong>机制说明</strong>：</p>
        <ul>
          <li>仅保存用户主动确认的事实，不自动将情绪推测作为事实持久化；</li>
          <li>同类事实更新值即可完成记忆纠正；</li>
          <li>关闭记忆不等于清空已有数据；</li>
          <li>会话删除不影响长期记忆。</li>
        </ul>
      </div>
    </div>
  );
};
