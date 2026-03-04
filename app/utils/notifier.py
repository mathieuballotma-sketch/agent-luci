import AppKit
import Foundation
import subprocess
import os
from .logger import logger

try:
    import UserNotifications
    HAS_UN = True
except ImportError:
    HAS_UN = False

def send_notification(title: str, message: str, filepath: str = None):
    """
    Envoie une notification macOS interactive avec son.
    Utilise UNUserNotificationCenter si disponible (macOS 10.14+), sinon NSUserNotification.
    En dernier recours, utilise osascript.
    """
    if HAS_UN:
        _send_via_un(title, message, filepath)
    else:
        _send_via_ns(title, message, filepath)

def _send_via_un(title: str, message: str, filepath: str = None):
    """Utilise UNUserNotificationCenter (moderne)."""
    center = UserNotifications.UNUserNotificationCenter.currentNotificationCenter()
    
    def check_auth(granted, error):
        if not granted:
            logger.warning("Notifications UN non autorisées, fallback sur NSUserNotification")
            _send_via_ns(title, message, filepath)
            return
        
        content = UserNotifications.UNMutableNotificationContent.alloc().init()
        content.setTitle_(title)
        content.setBody_(message)
        content.setSound_(UserNotifications.UNNotificationSound.defaultSound())
        
        if filepath:
            content.setUserInfo_({"filepath": filepath, "action": "open_file"})
            action = UserNotifications.UNNotificationAction.actionWithIdentifier_title_options_(
                "OPEN_ACTION", "Ouvrir", 1  # UNNotificationActionOptionForeground
            )
            category = UserNotifications.UNNotificationCategory.categoryWithIdentifier_actions_intentIdentifiers_options_(
                "OPEN_CATEGORY", [action], [], 1
            )
            center.setNotificationCategories_([category])
            content.setCategoryIdentifier_("OPEN_CATEGORY")
        
        request = UserNotifications.UNNotificationRequest.requestWithIdentifier_content_trigger_(
            f"notif_{title}_{message[:20]}", content, None
        )
        center.addNotificationRequest_withCompletionHandler_(request, lambda err: None)

    center.requestAuthorizationWithOptions_completionHandler_(
        3,  # UNAuthorizationOptionAlert + UNAuthorizationOptionSound
        check_auth
    )

def _send_via_ns(title: str, message: str, filepath: str = None):
    """Fallback sur NSUserNotification (ancien)."""
    try:
        notification = AppKit.NSUserNotification.alloc().init()
        notification.setTitle_(title)
        notification.setInformativeText_(message)
        notification.setSoundName_("NSUserNotificationDefaultSoundName")
        
        if filepath:
            notification.setActionButtonTitle_("Ouvrir")
            notification.setUserInfo_({"filepath": filepath, "action": "open_file"})
            notification.setHasActionButton_(True)
        else:
            notification.setHasActionButton_(False)

        centre = AppKit.NSUserNotificationCenter.defaultUserNotificationCenter()
        centre.scheduleNotification_(notification)
    except Exception as e:
        logger.warning(f"Échec notification NSUserNotification: {e}")
        _send_via_osascript(title, message, filepath)

def _send_via_osascript(title: str, message: str, filepath: str = None):
    """Ultime fallback avec osascript."""
    try:
        script = f'display notification "{message}" with title "{title}" sound name "default"'
        if filepath:
            script += f' subtitle "Cliquez pour ouvrir"'
        subprocess.run(['osascript', '-e', script], capture_output=True, timeout=5)
    except Exception as e:
        logger.error(f"Impossible d'envoyer la notification même avec osascript: {e}")