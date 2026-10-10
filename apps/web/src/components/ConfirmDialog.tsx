import { useEffect, useRef, type ReactNode } from 'react';

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  children?: ReactNode;
  confirmText: string;
  cancelText?: string;
  danger?: boolean;
  focusCancel?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export const ConfirmDialog = ({
  open,
  title,
  children,
  confirmText,
  cancelText = '取消',
  danger,
  focusCancel,
  busy,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) => {
  const restoreRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    restoreRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !busy) {
        onCancel();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
      restoreRef.current?.focus?.();
      restoreRef.current = null;
    };
  }, [open, busy, onCancel]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="alertdialog"
      aria-modal="true"
      aria-label={title}
    >
      {/* 遮罩层（毛玻璃半透明） */}
      <div
        className="absolute inset-0 bg-slate-900/40 backdrop-blur-xs transition-opacity animate-[fade-in_.15s_ease-out]"
        onClick={() => !busy && onCancel()}
      />

      {/* 弹窗主体 */}
      <div className="relative w-full max-w-sm rounded-2xl bg-white p-6 shadow-2xl border border-slate-200/80 animate-[fade-in_.2s_ease-out]">
        <h2 className="text-base font-semibold text-slate-900 tracking-tight">{title}</h2>
        {children && (
          <div className="mt-2 text-sm leading-relaxed text-slate-600">{children}</div>
        )}

        <div className="mt-6 flex justify-end gap-2.5">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            autoFocus={focusCancel}
            className="rounded-lg border border-slate-200 bg-white px-3.5 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 active:scale-95 transition disabled:opacity-60"
          >
            {cancelText}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            autoFocus={!focusCancel}
            className={`rounded-lg px-4 py-2 text-sm font-medium text-white shadow-xs active:scale-95 transition disabled:opacity-60 ${
              danger
                ? 'bg-rose-600 hover:bg-rose-700 focus:ring-2 focus:ring-rose-500/20'
                : 'bg-slate-900 hover:bg-slate-800 focus:ring-2 focus:ring-slate-900/20'
            }`}
          >
            {busy ? '处理中…' : confirmText}
          </button>
        </div>
      </div>
    </div>
  );
};

export default ConfirmDialog;
