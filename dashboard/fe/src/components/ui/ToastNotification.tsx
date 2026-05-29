'use client';


import { useNotificationStore, ToastMessage } from '@/lib/stores/notificationStore';
import { AnimatePresence, motion } from 'framer-motion';

const TOAST_ICONS = {
  info: 'info',
  success: 'check_circle',
  warning: 'warning',
  error: 'error',
};

const TOAST_COLORS = {
  info: 'border-blue-500 bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300',
  success: 'border-green-500 bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-300',
  warning: 'border-yellow-500 bg-yellow-50 dark:bg-yellow-900/20 text-yellow-700 dark:text-yellow-300',
  error: 'border-red-500 bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300',
};

const ToastItem = ({ toast }: { toast: ToastMessage }) => {
  const { removeToast } = useNotificationStore();

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 50, scale: 0.9 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, scale: 0.95, transition: { duration: 0.2 } }}
      className={`pointer-events-auto relative w-80 p-4 rounded-xl border-l-4 shadow-lg ${TOAST_COLORS[toast.type]} bg-white dark:bg-slate-900 flex gap-3 overflow-hidden group`}
    >
      <div className="flex-shrink-0">
        <span className="material-symbols-outlined text-xl">
          {TOAST_ICONS[toast.type]}
        </span>
      </div>
      <div className="flex-1 min-w-0">
        <h4 className="text-sm font-semibold truncate leading-tight mb-0.5">
          {toast.title}
        </h4>
        <p className="text-xs opacity-90 line-clamp-2 leading-relaxed">
          {toast.message}
        </p>
      </div>
      <button
        onClick={() => removeToast(toast.id)}
        className="flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded-lg hover:bg-black/5 dark:hover:bg-white/5"
      >
        <span className="material-symbols-outlined text-sm">close</span>
      </button>

      {/* Progress bar for auto-dismiss */}
      {toast.autoDismiss !== false && (
        <motion.div
          initial={{ width: '100%' }}
          animate={{ width: 0 }}
          transition={{ duration: 2, ease: 'linear' }}
          className="absolute bottom-0 left-0 h-0.5 bg-current opacity-20"
        />
      )}
    </motion.div>
  );
};

export const ToastNotification = () => {
  const { toasts } = useNotificationStore();

  return (
    <div className="fixed top-16 right-6 z-[100] flex flex-col gap-3 pointer-events-none">
      <AnimatePresence mode="popLayout">
        {toasts.map((toast) => (
          <div key={toast.id} className="pointer-events-auto">
            <ToastItem toast={toast} />
          </div>
        ))}
      </AnimatePresence>
    </div>
  );
};