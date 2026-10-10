import React from 'react';
import { Health } from '../api/types';

interface HeaderProps {
  isMockMode: boolean;
  onToggleMockMode: (mock: boolean) => void;
  health: Health | null;
  healthError: string | null;
  onRefreshHealth: () => void;
  // Mock 模拟故障开关
  simulate503?: boolean;
  onToggleSimulate503?: () => void;
  simulate409?: boolean;
  onToggleSimulate409?: () => void;
  onResetMockData?: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  isMockMode,
  onToggleMockMode,
  health,
  healthError,
  onRefreshHealth,
  simulate503,
  onToggleSimulate503,
  simulate409,
  onToggleSimulate409,
  onResetMockData,
}) => {
  return (
    <header className="app-header">
      <div className="header-brand-group">
        <h1 className="header-app-title">伴学 · 综合情感陪伴数字人</h1>
        <span className="header-subtitle">大学生日常情绪倾诉 · 事实记忆融合 · 离线轻量推理</span>
      </div>

      <div className="header-status-group">
        {/* 模式标识 */}
        <div className={`mode-badge ${isMockMode ? 'badge-mock' : 'badge-real'}`}>
          {isMockMode ? (
            <span className="badge-text-mock">⚠️ 演示数据模式 (纯前端 Mock)</span>
          ) : (
            <span className="badge-text-real">⚡ 真实后端模式 (FastAPI / 本地引擎)</span>
          )}
        </div>

        {/* 健康状态 */}
        <div className="health-status-badge">
          {healthError ? (
            <span className="health-offline" title={healthError}>
              🔴 后端离线 / 代理异常
            </span>
          ) : health ? (
            <span
              className={health.status === 'ok' ? 'health-ok' : 'health-degraded'}
              title={`模型状态: ${health.model_ready ? '就绪' : '未就绪'}, 版本: ${health.model_version}`}
            >
              {health.status === 'ok' ? '🟢 服务正常' : '🟡 服务降级 (未就绪)'}
              {health.is_mock && <span className="mock-sub-tag"> (stub)</span>}
            </span>
          ) : (
            <span className="health-checking">⚪ 检查服务中...</span>
          )}
          <button
            type="button"
            className="btn-refresh-health"
            onClick={onRefreshHealth}
            title="刷新服务健康状态"
          >
            ↻
          </button>
        </div>

        {/* 模式切换与控制 */}
        <div className="header-controls">
          <button
            type="button"
            className={`btn-mode-toggle ${isMockMode ? 'active-mock' : ''}`}
            onClick={() => onToggleMockMode(!isMockMode)}
            title="切换真实后端与纯本地 Mock 模式"
          >
            {isMockMode ? '切回真实模式' : '切到 Mock 模式'}
          </button>

          {isMockMode && onResetMockData && (
            <button
              type="button"
              className="btn-mock-tool"
              onClick={onResetMockData}
              title="重置纯前端本地演示数据到初始剧本状态"
            >
              重置演示数据
            </button>
          )}

          {isMockMode && onToggleSimulate503 && (
            <button
              type="button"
              className={`btn-mock-tool ${simulate503 ? 'active-danger' : ''}`}
              onClick={onToggleSimulate503}
              title="模拟 503 MODEL_UNAVAILABLE 故障"
            >
              {simulate503 ? '取消503' : '模拟503'}
            </button>
          )}

          {isMockMode && onToggleSimulate409 && (
            <button
              type="button"
              className={`btn-mock-tool ${simulate409 ? 'active-warning' : ''}`}
              onClick={onToggleSimulate409}
              title="模拟 409 TURN_IN_PROGRESS 冲突"
            >
              {simulate409 ? '取消409' : '模拟409'}
            </button>
          )}
        </div>
      </div>
    </header>
  );
};
