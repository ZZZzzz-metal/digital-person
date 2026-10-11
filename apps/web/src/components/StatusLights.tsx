import React from 'react';
import { Health } from '../api/types';

export type LightColor = 'green' | 'amber' | 'red' | 'gray';

interface StatusLightsProps {
  isMockMode: boolean;
  health: Health | null;
  healthError: string | null;
  memoryEnabled: boolean;
  onRefreshHealth: () => void;
  loading?: boolean;
}

const DOT_CLASS: Record<LightColor, string> = {
  green: 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]',
  amber: 'bg-amber-500 shadow-[0_0_8px_rgba(245,158,11,0.5)]',
  red: 'bg-rose-500 shadow-[0_0_8px_rgba(244,63,94,0.5)]',
  gray: 'bg-slate-300',
};

export const StatusLights: React.FC<StatusLightsProps> = ({
  isMockMode,
  health,
  healthError,
  memoryEnabled,
  onRefreshHealth,
  loading = false,
}) => {
  const serviceLight: { label: string; color: LightColor; tip: string } = isMockMode
    ? {
        label: 'Mock引擎',
        color: 'green',
        tip: '前端独立运行模式：所有会话与记忆数据均在本地处理，刷新可保留修改',
      }
    : healthError
    ? {
        label: '服务离线',
        color: 'red',
        tip: `后端连接异常: ${healthError}。请检查本地 FastAPI 服务 (127.0.0.1:8000)`,
      }
    : health
    ? {
        label: health.status === 'ok' ? '后端正常' : '服务降级',
        color: health.status === 'ok' ? 'green' : 'amber',
        tip: `FastAPI 后端状态: ${health.status} (${health.is_mock ? 'Stub 模拟' : '真实推理'})`,
      }
    : {
        label: '服务检测',
        color: 'gray',
        tip: '正在检测后端健康状态...',
      };

  const modelLight: { label: string; color: LightColor; tip: string } = isMockMode
    ? {
        label: '剧本模型',
        color: 'green',
        tip: '离线规则与多轮剧本匹配模型已就绪 (mock-web-v1)',
      }
    : health
    ? {
        label: health.model_ready ? '模型就绪' : '模型未就绪',
        color: health.model_ready ? 'green' : 'red',
        tip: `数字人伴学模型引擎: ${health.model_ready ? '已就绪' : '未就绪'}, 版本: ${health.model_version}`,
      }
    : {
        label: '模型',
        color: 'gray',
        tip: '模型引擎状态检查中',
      };

  const memoryLight: { label: string; color: LightColor; tip: string } = {
    label: memoryEnabled ? '记忆开启' : '记忆停用',
    color: memoryEnabled ? 'green' : 'gray',
    tip: memoryEnabled
      ? '长期事实记忆功能开启：对话中自动检索并注入相关事实'
      : '记忆功能已关闭：事实保留在库中，但对话中不检索，亦不可新增',
  };

  const lights = [serviceLight, modelLight, memoryLight];

  return (
    <div className="flex items-center gap-1 sm:gap-2" aria-label="系统运行状态">
      <ul className="flex items-center gap-1 sm:gap-2">
        {lights.map((l, idx) => (
          <li key={idx} className="group relative">
            <button
              type="button"
              className="flex items-center gap-1.5 rounded-md px-1.5 py-1 text-xs text-slate-600 hover:bg-slate-100 focus:bg-slate-100 focus:outline-none transition cursor-default sm:px-2"
              aria-label={l.tip}
              title={l.tip}
            >
              <span className={`h-2 w-2 rounded-full transition-colors duration-300 ${DOT_CLASS[l.color]}`} />
              <span className="hidden sm:inline font-medium text-slate-600">{l.label}</span>
            </button>
            {/* Tooltip 浮层 */}
            <span
              role="tooltip"
              className="pointer-events-none absolute right-0 top-full z-40 mt-1.5 hidden w-max max-w-64 rounded-lg bg-slate-900 px-3 py-2 text-xs leading-relaxed text-slate-100 shadow-xl group-hover:block group-focus-within:block transition animate-[fade-in_.15s_ease-out]"
            >
              {l.tip}
            </span>
          </li>
        ))}
      </ul>

      {/* 刷新按钮 */}
      <button
        type="button"
        className={`rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition ${
          loading ? 'animate-spin text-slate-700' : ''
        }`}
        onClick={onRefreshHealth}
        title="立即刷新系统健康检查状态"
        aria-label="刷新状态"
      >
        <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
          <path d="M3 3v5h5" />
          <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" />
          <path d="M16 21h5v-5" />
        </svg>
      </button>
    </div>
  );
};

export default StatusLights;
