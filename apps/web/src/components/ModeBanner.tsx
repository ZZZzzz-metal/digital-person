import React, { useState } from 'react';
import { Health } from '../api/types';

interface ModeBannerProps {
  isMockMode: boolean;
  onToggleMockMode: (mock: boolean) => void;
  health: Health | null;
  healthError: string | null;
  onResetMockData: () => void;
  onRefreshHealth: () => void;
}

export const ModeBanner: React.FC<ModeBannerProps> = ({
  isMockMode,
  onToggleMockMode,
  health,
  healthError,
  onResetMockData,
  onRefreshHealth,
}) => {
  const [dismissedMock, setDismissedMock] = useState(false);

  // 1. 真实后端模式下连接失败
  if (!isMockMode && healthError) {
    return (
      <div
        role="alert"
        className="border-b border-rose-200 bg-rose-50 text-rose-900 px-4 py-2 animate-[fade-in_.2s_ease-out]"
      >
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-2 text-xs">
          <div className="flex items-center gap-2">
            <svg
              className="h-4 w-4 shrink-0 text-rose-600"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
            >
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            <span>
              <strong>未连接到本地 FastAPI 后端 (127.0.0.1:8000)</strong>：
              {healthError}。您可启动后端服务，或一键切换至纯前端离线 Mock 模式进行体验。
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="rounded-md border border-rose-300 bg-white px-2.5 py-1 font-medium text-rose-700 hover:bg-rose-50 active:scale-95 transition"
              onClick={onRefreshHealth}
            >
              重试连接
            </button>
            <button
              type="button"
              className="rounded-md bg-rose-600 px-2.5 py-1 font-medium text-white hover:bg-rose-700 active:scale-95 transition"
              onClick={() => onToggleMockMode(true)}
            >
              一键切到 Mock 模式
            </button>
          </div>
        </div>
      </div>
    );
  }

  // 2. 纯前端 Mock 模式说明黄条
  if (isMockMode && !dismissedMock) {
    return (
      <div
        role="status"
        className="border-b border-amber-200 bg-amber-50 text-amber-900 px-4 py-2 animate-[fade-in_.2s_ease-out]"
      >
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-2 text-xs">
          <div className="flex items-center gap-2">
            <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-amber-200 text-amber-800 font-bold text-[11px]">
              !
            </span>
            <span>
              <strong>演示数据模式 (纯前端 Mock)</strong>：所有会话、聊天与事实记忆修改均保存在浏览器本地，页面刷新保留修改。如需重置为初始预设剧本可点击右侧按钮。
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="rounded-md border border-amber-300 bg-white px-2.5 py-1 font-medium text-amber-800 hover:bg-amber-100/50 active:scale-95 transition"
              onClick={onResetMockData}
            >
              重置演示数据
            </button>
            <button
              type="button"
              className="rounded-md bg-slate-900 px-2.5 py-1 font-medium text-white hover:bg-slate-800 active:scale-95 transition"
              onClick={() => onToggleMockMode(false)}
            >
              切回真实模式
            </button>
            <button
              type="button"
              className="p-1 text-amber-600 hover:text-amber-800 rounded transition"
              onClick={() => setDismissedMock(true)}
              title="暂时收起提示"
              aria-label="关闭提示"
            >
              <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    );
  }

  // 3. 真实模式下若是后端 Stub
  if (!isMockMode && health?.is_mock) {
    return (
      <div
        role="status"
        className="border-b border-sky-200 bg-sky-50 text-sky-900 px-4 py-1.5 animate-[fade-in_.2s_ease-out]"
      >
        <div className="mx-auto flex max-w-7xl items-center justify-between text-xs">
          <span>
            ℹ️ 后端当前以 Stub 模拟引擎运行，返回的数据带有 <code>is_mock: true</code> 演示标识。
          </span>
        </div>
      </div>
    );
  }

  return null;
};

export default ModeBanner;
