import React from 'react';
import { useAppState } from '../../hooks/useAppState';
import { CheckCircle2, Info, AlertTriangle, AlertCircle, X } from 'lucide-react';
import type { NotificationType } from '../../context/AppStateProvider';

const ICON_MAP: Record<NotificationType, React.ElementType> = {
  success: CheckCircle2,
  info: Info,
  warning: AlertTriangle,
  error: AlertCircle,
};

export const NotificationContainer: React.FC = () => {
  const { notifications, dismissNotification } = useAppState();

  if (notifications.length === 0) return null;

  return (
    <div className="global-notification-overlay" aria-live="polite">
      {notifications.map((notif) => {
        const IconComponent = ICON_MAP[notif.type] || Info;

        return (
          <div
            key={notif.id}
            className={`global-notification-item ${notif.type}`}
            role="alert"
          >
            <div className="notif-icon-box">
              <IconComponent size={16} />
            </div>

            <div className="notif-body">
              {notif.title && <span className="notif-title">{notif.title}</span>}
              <span className="notif-message">{notif.message}</span>
            </div>

            <button
              type="button"
              className="notif-close-btn"
              onClick={() => dismissNotification(notif.id)}
              aria-label="Dismiss notification"
            >
              <X size={14} />
            </button>
          </div>
        );
      })}
    </div>
  );
};
