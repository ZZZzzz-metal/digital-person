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
}

const AVATAR_MAP: Record<Expression, string> = {
  neutral: neutralSvg,
  smile: smileSvg,
  concern: concernSvg,
  listening: listeningSvg,
};

export const AvatarDisplay: React.FC<AvatarDisplayProps> = ({
  expression,
  emotion = 'neutral',
  modelVersion = 'baseline-v1',
  elapsedMs,
  isMock = false,
  onSelectExpressionPreview,
}) => {
  const currentSvg = AVATAR_MAP[expression] || AVATAR_MAP.neutral;

  return (
    <div className="avatar-panel">
      <div className="avatar-image-container">
        <img
          src={currentSvg}
          alt={`数字人表情: ${EXPRESSION_LABELS[expression] || expression}`}
          className="avatar-image"
        />
        {isMock && <div className="mock-badge-floating">演示数据</div>}
      </div>

      <div className="avatar-meta">
        <div className="badge-row">
          <span className={`status-badge expression-${expression}`}>
            表情: {EXPRESSION_LABELS[expression] || expression}
          </span>
          <span className="status-badge emotion-badge">
            情绪估计: {EMOTION_LABELS[emotion] || emotion}
          </span>
        </div>

        <div className="model-info-row">
          <span className="info-text">模型版本: <code>{modelVersion}</code></span>
          {typeof elapsedMs === 'number' && (
            <span className="info-text">耗时: <code>{elapsedMs} ms</code></span>
          )}
        </div>
      </div>

      {onSelectExpressionPreview && (
        <div className="expression-preview-controls">
          <span className="preview-label">表情快速演示:</span>
          {(['neutral', 'smile', 'concern', 'listening'] as Expression[]).map((exp) => (
            <button
              key={exp}
              type="button"
              className={`btn-preview ${expression === exp ? 'active' : ''}`}
              onClick={() => onSelectExpressionPreview(exp)}
            >
              {EXPRESSION_LABELS[exp]}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};
