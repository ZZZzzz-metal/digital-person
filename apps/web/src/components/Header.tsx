import React from 'react';
import { Health } from '../api/types';
import StatusLights from './StatusLights';

interface HeaderProps {
  isMockMode: boolean;
  onToggleMockMode: (mock: boolean) => void;
  health: Health | null;
  healthError: string | null;
  memoryEnabled: boolean;
  onRefreshHealth: () => void;
  simulate503?: boolean;
  onToggleSimulate503?: () => void;
  simulate409?: boolean;
  onToggleSimulate409?: () => void;
  onResetMockData?: () => void;
  healthRefreshing?: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  isMockMode,
  onToggleMockMode,
  health,
  healthError,
  memoryEnabled,
  onRefreshHealth,
  simulate503,
  onToggleSimulate503,
  simulate409,
  onToggleSimulate409,
  onResetMockData,
  healthRefreshing = false,
}) => {
  return (
    <header className="sticky top-0 z-30 border-b border-slate-200/80 bg-white/90 backdrop-blur-md">
      <div className="mx-auto flex h-14 w-full items-center justify-between gap-3 px-4 sm:px-6">
        {/* 左侧：品牌 Logo 与说明 */}
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-slate-900 text-white shadow-xs">
            <svg
              className="h-5 w-5"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              {/* 人形/陪伴小图标 */}
              <path d="M12 2a5 5 0 0 1 5 5v1a5 5 0 0 1-10 0V7a5 5 0 0 1 5-5Z" />
              <path d="M3 21v-2a7 7 0 0 1 14 0v2" />
              <path d="M19 11v6" />
              <path d="M22 14h-6" />
            </svg>
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-base font-semibold tracking-tight text-slate-900 truncate">
                伴学 · 综合情感陪伴数字人
              </span>
              {/* 模式标签 */}
              <span
                className={`hidden md:inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium border ${
                  isMockMode || health?.is_mock
                    ? 'bg-amber-50 text-amber-800 border-amber-200'
                    : 'bg-emerald-50 text-emerald-800 border-emerald-200'
                }`}
                title={
                  isMockMode
                    ? '纯前端本地 Mock 模式：页面刷新保留本地修改，点击「重置演示数据」可恢复初始剧本状态'
                    : health?.is_mock
                    ? '后端当前运行在 Stub 模式，响应带有 is_mock: true 演示标识'
                    : '真实后端模式：连接本地 FastAPI 服务与离线模型推理引擎'
                }
              >
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    isMockMode || health?.is_mock ? 'bg-amber-500' : 'bg-emerald-500'
                  }`}
                />
                {isMockMode
                  ? '演示数据模式 (纯前端 Mock)'
                  : health?.is_mock
                  ? '演示数据 (后端 Stub)'
                  : '真实后端模式 (FastAPI)'}
              </span>
            </div>
            <p className="hidden lg:block text-xs text-slate-500 truncate">
              大学生日常情绪倾诉 · 事实记忆融合 · 本地轻量推理
            </p>
          </div>
        </div>

        {/* 右侧：状态指示灯与控制按钮 */}
        <div className="flex items-center gap-2 sm:gap-3 shrink-0">
          <StatusLights
            isMockMode={isMockMode}
            health={health}
            healthError={healthError}
            memoryEnabled={memoryEnabled}
            onRefreshHealth={onRefreshHealth}
            loading={healthRefreshing}
          />

          <div className="h-4 w-[1px] bg-slate-200 mx-0.5 hidden sm:block" />

          {/* 模式切换与 Mock 专属调试控制 */}
          <div className="flex items-center gap-1.5 sm:gap-2">
            {isMockMode && onResetMockData && (
              <button
                type="button"
                className="hidden md:inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 hover:text-slate-900 active:scale-95 transition"
                onClick={onResetMockData}
                title="重置纯前端本地演示数据到初始剧本状态"
              >
                <svg className="h-3.5 w-3.5 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                  <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
                  <path d="M3 3v5h5" />
                </svg>
                重置演示数据
              </button>
            )}

            {isMockMode && onToggleSimulate503 && (
              <button
                type="button"
                className={`rounded-lg px-2.5 py-1.5 text-xs font-medium transition active:scale-95 ${
                  simulate503
                    ? 'bg-rose-100 text-rose-700 border border-rose-300 font-semibold'
                    : 'border border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
                }`}
                onClick={onToggleSimulate503}
                title="模拟 503 MODEL_UNAVAILABLE 模型未就绪故障"
              >
                {simulate503 ? '503 模拟中' : '模拟 503'}
              </button>
            )}

            {isMockMode && onToggleSimulate409 && (
              <button
                type="button"
                className={`rounded-lg px-2.5 py-1.5 text-xs font-medium transition active:scale-95 ${
                  simulate409
                    ? 'bg-amber-100 text-amber-800 border border-amber-300 font-semibold'
                    : 'border border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
                }`}
                onClick={onToggleSimulate409}
                title="模拟 409 TURN_IN_PROGRESS 冲突"
              >
                {simulate409 ? '409 模拟中' : '模拟 409'}
              </button>
            )}

            {/* 真实/Mock 切换主按钮 */}
            <button
              type="button"
              className={`rounded-lg px-3 py-1.5 text-xs font-medium transition active:scale-95 ${
                isMockMode
                  ? 'bg-slate-900 text-white hover:bg-slate-800 shadow-xs'
                  : 'border border-slate-200 bg-white text-slate-700 hover:bg-slate-50 shadow-xs'
              }`}
              onClick={() => onToggleMockMode(!isMockMode)}
              title="切换真实后端与纯本地 Mock 模式"
            >
              {isMockMode ? '切回真实模式' : '切到 Mock 模式'}
            </button>
          </div>
        </div>
      </div>
    </header>
  );
};

export default Header;
