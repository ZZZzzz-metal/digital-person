import React from 'react';
import { Emotion, Expression, EMOTION_LABELS, EXPRESSION_LABELS } from '../api/types';
import neutralSvg from '../assets/neutral.svg';
import smileSvg from '../assets/smile.svg';
import concernSvg from '../assets/concern.svg';
import listeningSvg from '../assets/listening.svg';

interface AvatarDisplayProps {
  expression: Expression;
  emotion?: Emotion;
  modelVersion?: string;
  elapsedMs?: number;
  isMock?: boolean;
  onSelectExpressionPreview?: (exp: Expression) => void;
  className?: string;
}

const AVATAR_MAP: Record<Expression, string> = {
  neutral: neutralSvg,
  smile: smileSvg,
  concern: concernSvg,
  listening: listeningSvg,
};

const EXPRESSION_BADGE_STYLE: Record<Expression, string> = {
  neutral: 'bg-slate-100 text-slate-800 border-slate-200',
  smile: 'bg-emerald-50 text-emerald-800 border-emerald-200',
  concern: 'bg-amber-50 text-amber-800 border-amber-200',
  listening: 'bg-sky-50 text-sky-800 border-sky-200',
};

const EMOTION_BADGE_STYLE: Record<Emotion, string> = {
  neutral: 'bg-slate-50 text-slate-700 border-slate-200',
  happy: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  sad: 'bg-indigo-50 text-indigo-700 border-indigo-200',
  anxious: 'bg-amber-50 text-amber-700 border-amber-200',
  angry: 'bg-rose-50 text-rose-700 border-rose-200',
  unknown: 'bg-slate-50 text-slate-500 border-slate-200',
};

const EXPRESSION_SHORT: Record<Expression, string> = {
  neutral: '平静',
  smile: '微笑',
  concern: '关切',
  listening: '倾听',
};

export const AvatarDisplay: React.FC<AvatarDisplayProps> = ({
  expression,
  emotion = 'neutral',
  modelVersion = 'baseline-v1',
  elapsedMs,
  isMock = false,
  onSelectExpressionPreview,
  className = '',
}) => {
  const safeExpression: Expression =
    expression && AVATAR_MAP[expression] ? expression : 'neutral';
  const currentSvg = AVATAR_MAP[safeExpression];

  return (
    <div className={`rounded-2xl border border-slate-200/80 bg-white p-5 shadow-xs transition hover:shadow-sm ${className}`}>
      {/* 头部标题与当前情绪 */}
      <div className="flex items-center justify-between pb-3 border-b border-slate-100">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-slate-900 tracking-tight">数字人状态</h3>
          <span className="text-[11px] text-slate-400">实时表情联动</span>
        </div>
        <span
          className={`rounded-full px-2.5 py-0.5 text-xs font-medium border ${
            EMOTION_BADGE_STYLE[emotion] || EMOTION_BADGE_STYLE.neutral
          }`}
          title="模型上一轮识别的用户情绪"
        >
          感知情绪: {EMOTION_LABELS[emotion] || emotion}
        </span>
      </div>

      {/* 数字人头像视窗 */}
      <div className="relative mt-4 flex flex-col items-center justify-center">
        <div className="relative h-44 w-44 sm:h-48 sm:w-48 rounded-full p-2 bg-gradient-to-b from-slate-100 via-slate-50 to-white border border-slate-200/70 shadow-inner flex items-center justify-center overflow-hidden">
          <img
            src={currentSvg}
            alt={`数字人表情: ${EXPRESSION_LABELS[safeExpression]}`}
            className="h-full w-full object-contain transition-all duration-300 animate-[avatar-breathe_4s_ease-in-out_infinite]"
          />
          {isMock && (
            <div className="absolute top-3 right-3 rounded-md bg-amber-500/90 text-[10px] font-bold text-white px-2 py-0.5 shadow-xs">
              演示数据
            </div>
          )}
        </div>

        {/* 当前表情状态药丸 */}
        <div className="mt-3 flex items-center gap-2">
          <span
            className={`rounded-full px-3 py-1 text-xs font-semibold border ${
              EXPRESSION_BADGE_STYLE[safeExpression]
            }`}
          >
            表情: {EXPRESSION_LABELS[safeExpression]}
          </span>
        </div>
      </div>

      {/* 模型与耗时遥测 */}
      <div className="mt-4 pt-3 border-t border-slate-100 grid grid-cols-2 gap-2 text-[11px] text-slate-500">
        <div className="rounded-lg bg-slate-50 p-2 border border-slate-100">
          <span className="text-slate-400 block text-[10px]">模型版本</span>
          <span className="font-mono font-medium text-slate-700 truncate block" title={modelVersion}>
            {modelVersion}
          </span>
        </div>
        <div className="rounded-lg bg-slate-50 p-2 border border-slate-100">
          <span className="text-slate-400 block text-[10px]">推理耗时</span>
          <span className="font-mono font-medium text-slate-700 block">
            {typeof elapsedMs === 'number' ? `${elapsedMs} ms` : '待对话'}
          </span>
        </div>
      </div>

      {/* 表情快速演示（四种状态一键切换） */}
      {onSelectExpressionPreview && (
        <div className="mt-4 pt-3 border-t border-slate-100">
          <span className="text-[11px] font-medium text-slate-500 block mb-2">
            表情快速演示 (4 状态联动)：
          </span>
          <div className="grid grid-cols-4 gap-1.5">
            {(['neutral', 'smile', 'concern', 'listening'] as Expression[]).map((exp) => (
              <button
                key={exp}
                type="button"
                className={`rounded-lg py-1.5 text-xs font-medium transition active:scale-95 ${
                  expression === exp
                    ? 'bg-slate-900 text-white shadow-xs font-semibold'
                    : 'border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 hover:text-slate-900'
                }`}
                onClick={() => onSelectExpressionPreview(exp)}
                title={`切换为 ${EXPRESSION_LABELS[exp]}`}
              >
                {EXPRESSION_SHORT[exp]}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default AvatarDisplay;
