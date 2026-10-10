import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react';

export type ToastTone = 'info' | 'error' | 'success';

interface Action {
  label: string;
  onClick: () => void;
}

interface Item {
  id: number;
  text: string;
  tone: ToastTone;
  action?: Action;
  leaving: boolean;
}

const MAX_VISIBLE = 2;
const DURATION = 3000;
const ACTION_DURATION = 6000;
const LEAVE_MS = 300;

export type ToastFn = (text: string, tone?: ToastTone, action?: Action) => void;

const ToastContext = createContext<ToastFn>(() => {});

export function useToast(): ToastFn {
  return useContext(ToastContext);
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Item[]>([]);
  const listRef = useRef<Item[]>([]);
  const nextId = useRef(1);
  const timers = useRef<
    Map<number, { expireAt: number; remaining: number; timer: ReturnType<typeof setTimeout> }>
  >(new Map());

  const update = useCallback((fn: (list: Item[]) => Item[]) => {
    listRef.current = fn(listRef.current);
    setItems(listRef.current);
  }, []);

  const dismiss = useCallback(
    (ids: number[]) => {
      if (ids.length === 0) return;
      update((list) => list.map((x) => (ids.includes(x.id) ? { ...x, leaving: true } : x)));
      setTimeout(() => update((list) => list.filter((x) => !ids.includes(x.id))), LEAVE_MS);
      for (const id of ids) {
        const t = timers.current.get(id);
        if (t) clearTimeout(t.timer);
        timers.current.delete(id);
      }
    },
    [update]
  );

  const schedule = useCallback(
    (id: number, ms: number) => {
      const timer = setTimeout(() => dismiss([id]), ms);
      timers.current.set(id, { expireAt: Date.now() + ms, remaining: ms, timer });
    },
    [dismiss]
  );

  const pause = useCallback((id: number) => {
    const t = timers.current.get(id);
    if (!t) return;
    clearTimeout(t.timer);
    t.remaining = Math.max(0, t.expireAt - Date.now());
  }, []);

  const resume = useCallback(
    (id: number) => {
      const t = timers.current.get(id);
      if (!t) return;
      t.expireAt = Date.now() + t.remaining;
      t.timer = setTimeout(() => dismiss([id]), Math.max(300, t.remaining));
    },
    [dismiss]
  );

  const show = useCallback(
    (text: string, tone: ToastTone = 'info', action?: Action) => {
      const id = nextId.current++;
      update((list) => [
        ...list.filter((x) => x.leaving || x.text !== text),
        { id, text, tone, action, leaving: false },
      ]);
      const alive = listRef.current.filter((x) => !x.leaving);
      dismiss(alive.slice(0, Math.max(0, alive.length - MAX_VISIBLE)).map((x) => x.id));
      schedule(id, action ? ACTION_DURATION : DURATION);
    },
    [update, dismiss, schedule]
  );

  return (
    <ToastContext.Provider value={show}>
      {children}
      {/* 手机上底部有 Tab 栏，往上让出空间 */}
      <div className="pointer-events-none fixed inset-x-0 bottom-20 md:bottom-8 z-50 flex flex-col items-center px-4">
        {items.map((t) => (
          <div
            key={t.id}
            role={t.tone === 'error' ? 'alert' : 'status'}
            className={
              t.leaving
                ? 'animate-[toast-leave_.3s_ease-in_forwards] overflow-hidden'
                : 'animate-[toast-enter_.2s_ease-out] pt-2'
            }
          >
            <div
              className={`pointer-events-auto flex items-center gap-3 rounded-xl px-4 py-2.5 text-sm font-medium text-white shadow-xl transition-all ${
                t.tone === 'error'
                  ? 'bg-rose-600'
                  : t.tone === 'success'
                  ? 'bg-emerald-700'
                  : 'bg-slate-900'
              }`}
              onMouseEnter={() => pause(t.id)}
              onMouseLeave={() => resume(t.id)}
              onFocus={() => pause(t.id)}
              onBlur={() => resume(t.id)}
            >
              {t.tone === 'success' && (
                <svg className="h-4 w-4 shrink-0 text-emerald-300" viewBox="0 0 20 20" fill="currentColor">
                  <path
                    fillRule="evenodd"
                    d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                    clipRule="evenodd"
                  />
                </svg>
              )}
              {t.tone === 'error' && (
                <svg className="h-4 w-4 shrink-0 text-rose-200" viewBox="0 0 20 20" fill="currentColor">
                  <path
                    fillRule="evenodd"
                    d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z"
                    clipRule="evenodd"
                  />
                </svg>
              )}
              <span>{t.text}</span>
              {t.action && (
                <button
                  type="button"
                  className="-mr-1 rounded px-2 py-0.5 text-xs font-semibold text-sky-300 hover:bg-white/10 active:scale-95 transition"
                  onClick={() => {
                    t.action!.onClick();
                    dismiss([t.id]);
                  }}
                >
                  {t.action.label}
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
