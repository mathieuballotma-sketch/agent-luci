import objc
from PyObjCTools import AppHelper
import AppKit
import Quartz
import Foundation
import threading
import sys
import subprocess
import os
import time
from ..core.engine import LucidEngine
from ..core.config import Config

print("📦 Chargement du module hud_native")

WINDOW_W = 420
WINDOW_H = 460
CORNER_R = 24.0
PADDING  = 16
HEADER_H = 56
INPUT_H  = 38
STATUS_H = 16
ALPHA    = 0.75

def ns_color(r, g, b, a=1.0):
    return AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, a)

def ns_white(w, a=1.0):
    return AppKit.NSColor.colorWithCalibratedWhite_alpha_(w, a)

def make_rect(x, y, w, h):
    return AppKit.NSMakeRect(x, y, w, h)

class DraggableView(AppKit.NSView):
    def initWithFrame_(self, frame):
        self = objc.super(DraggableView, self).initWithFrame_(frame)
        if self is not None:
            self._drag_start = None
        return self

    def mouseDown_(self, event):
        self._drag_start = event.locationInWindow()

    def mouseDragged_(self, event):
        if self._drag_start is None:
            return
        loc = event.locationInWindow()
        dx = loc.x - self._drag_start.x
        dy = loc.y - self._drag_start.y
        win = self.window()
        if win:
            f = win.frame()
            win.setFrameOrigin_((f.origin.x + dx, f.origin.y + dy))

    def mouseUp_(self, event):
        self._drag_start = None

    def isOpaque(self):
        return False

class ThinkingIndicatorView(AppKit.NSView):
    """Indicateur animé (point qui pulse)"""
    def initWithFrame_(self, frame):
        self = objc.super(ThinkingIndicatorView, self).initWithFrame_(frame)
        if self is not None:
            self.setWantsLayer_(True)
            self.layer().setBackgroundColor_(ns_white(1.0, 0.0).CGColor())
            self.layer().setCornerRadius_(frame.size.width / 2)
            self.layer().setMasksToBounds_(True)
        return self

    def startAnimating(self):
        self.layer().setBackgroundColor_(ns_color(0.3, 0.6, 1.0, 0.9).CGColor())
        anim = Quartz.CABasicAnimation.animationWithKeyPath_("transform.scale")
        anim.setFromValue_(1.0)
        anim.setToValue_(1.4)
        anim.setDuration_(0.8)
        anim.setAutoreverses_(True)
        anim.setRepeatCount_(float('inf'))
        self.layer().addAnimation_forKey_(anim, "pulse")

    def stopAnimating(self):
        self.layer().removeAllAnimations()
        self.layer().setBackgroundColor_(ns_white(1.0, 0.2).CGColor())

class HUDWindow(AppKit.NSPanel):
    def init(self):
        rect = make_rect(
            100,
            AppKit.NSScreen.mainScreen().frame().size.height - WINDOW_H - 100,
            WINDOW_W,
            WINDOW_H
        )
        style = (
            AppKit.NSWindowStyleMaskBorderless |
            AppKit.NSWindowStyleMaskNonactivatingPanel
        )
        self = objc.super(HUDWindow, self).initWithContentRect_styleMask_backing_defer_(
            rect, style, AppKit.NSBackingStoreBuffered, False
        )
        if self is None:
            return None

        self.setFloatingPanel_(True)
        self.setBecomesKeyOnlyIfNeeded_(False)
        self.setHidesOnDeactivate_(False)
        self.setLevel_(Quartz.kCGFloatingWindowLevel + 1)
        self.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces     |
            AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary  |
            AppKit.NSWindowCollectionBehaviorStationary           |
            AppKit.NSWindowCollectionBehaviorIgnoresCycle
        )
        self.setOpaque_(False)
        self.setBackgroundColor_(AppKit.NSColor.clearColor())
        self.setAlphaValue_(ALPHA)
        self.setHasShadow_(True)

        self._is_dragging  = False
        self._is_processing = False
        self._processing_start_time = 0

        self._setup_ui()
        self._setup_space_observer()
        self._setup_watchdog()

        # Variables pour la surveillance de la frappe
        self._typing_timer = None
        self._last_text = ""

        print("✅ HUDPanel initialisé avec effet verre")
        return self

    def canBecomeKeyWindow(self):
        return True

    def canBecomeMainWindow(self):
        return True

    def _setup_ui(self):
        content = self.contentView()
        content.setWantsLayer_(True)
        content.layer().setCornerRadius_(CORNER_R)
        content.layer().setMasksToBounds_(True)

        # Effet verre (vibrancy)
        vfx = AppKit.NSVisualEffectView.alloc().initWithFrame_(
            make_rect(0, 0, WINDOW_W, WINDOW_H)
        )
        vfx.setMaterial_(AppKit.NSVisualEffectMaterialHUDWindow)
        vfx.setBlendingMode_(AppKit.NSVisualEffectBlendingModeBehindWindow)
        vfx.setState_(AppKit.NSVisualEffectStateActive)
        vfx.setWantsLayer_(True)
        vfx.layer().setCornerRadius_(CORNER_R)
        vfx.layer().setBorderWidth_(0.5)
        vfx.layer().setBorderColor_(ns_white(0.3, 0.2).CGColor())
        content.addSubview_(vfx)

        # Vue pour le drag (par-dessus)
        drag_view = DraggableView.alloc().initWithFrame_(
            make_rect(0, 0, WINDOW_W, WINDOW_H)
        )
        content.addSubview_(drag_view)

        # En-tête avec icône, indicateur et titre
        icon_label = AppKit.NSTextField.alloc().initWithFrame_(
            make_rect(16, WINDOW_H - HEADER_H + 16, 28, 22)
        )
        icon_label.setStringValue_("✦")
        icon_label.setEditable_(False)
        icon_label.setBezeled_(False)
        icon_label.setDrawsBackground_(False)
        icon_label.setFont_(
            AppKit.NSFont.systemFontOfSize_weight_(20, AppKit.NSFontWeightLight)
        )
        icon_label.setTextColor_(ns_white(0.9, 0.8))
        content.addSubview_(icon_label)

        # Titre
        title = AppKit.NSTextField.alloc().initWithFrame_(
            make_rect(48, WINDOW_H - HEADER_H + 16, 100, 22)
        )
        title.setStringValue_("LUCIDE")
        title.setEditable_(False)
        title.setBezeled_(False)
        title.setDrawsBackground_(False)
        title.setFont_(
            AppKit.NSFont.monospacedDigitSystemFontOfSize_weight_(
                16, AppKit.NSFontWeightRegular
            )
        )
        title.setTextColor_(ns_white(0.95, 0.9))
        content.addSubview_(title)

        # Indicateur de réflexion (point animé)
        indicator_size = 12
        indicator_x = 48 + 100 + 12
        indicator_y = WINDOW_H - HEADER_H + 16 + (22 - indicator_size) / 2
        self._thinking_indicator = ThinkingIndicatorView.alloc().initWithFrame_(
            make_rect(indicator_x, indicator_y, indicator_size, indicator_size)
        )
        content.addSubview_(self._thinking_indicator)

        # Label de statut "En cours de réflexion"
        self._thinking_label = AppKit.NSTextField.alloc().initWithFrame_(
            make_rect(indicator_x + indicator_size + 8, WINDOW_H - HEADER_H + 16, 140, 22)
        )
        self._thinking_label.setStringValue_("")
        self._thinking_label.setEditable_(False)
        self._thinking_label.setBezeled_(False)
        self._thinking_label.setDrawsBackground_(False)
        self._thinking_label.setFont_(
            AppKit.NSFont.systemFontOfSize_(11)
        )
        self._thinking_label.setTextColor_(ns_white(0.7, 0.8))
        self._thinking_label.setAlphaValue_(0.0)
        content.addSubview_(self._thinking_label)

        # Latence
        self._latency_label = AppKit.NSTextField.alloc().initWithFrame_(
            make_rect(WINDOW_W - 90, WINDOW_H - HEADER_H + 17, 80, 18)
        )
        self._latency_label.setStringValue_("")
        self._latency_label.setEditable_(False)
        self._latency_label.setBezeled_(False)
        self._latency_label.setDrawsBackground_(False)
        self._latency_label.setAlignment_(AppKit.NSTextAlignmentRight)
        self._latency_label.setFont_(
            AppKit.NSFont.monospacedDigitSystemFontOfSize_weight_(
                10, AppKit.NSFontWeightLight
            )
        )
        self._latency_label.setTextColor_(ns_white(0.5, 0.7))
        content.addSubview_(self._latency_label)

        # Séparateur
        sep = AppKit.NSBox.alloc().initWithFrame_(
            make_rect(PADDING, WINDOW_H - HEADER_H - 2, WINDOW_W - 2 * PADDING, 1)
        )
        sep.setBoxType_(AppKit.NSBoxSeparator)
        sep.setAlphaValue_(0.15)
        content.addSubview_(sep)

        # Zone de texte (historique)
        text_y = INPUT_H + STATUS_H + PADDING * 2 + 10
        text_h = WINDOW_H - HEADER_H - text_y - PADDING
        text_w = WINDOW_W - PADDING * 2

        self._text_view = AppKit.NSTextView.alloc().initWithFrame_(
            make_rect(0, 0, text_w, 9999)
        )
        self._text_view.setEditable_(False)
        self._text_view.setSelectable_(True)
        self._text_view.setBackgroundColor_(AppKit.NSColor.clearColor())
        self._text_view.setTextColor_(ns_white(0.92, 0.9))
        self._text_view.setFont_(AppKit.NSFont.systemFontOfSize_(12.5))
        self._text_view.textContainer().setLineFragmentPadding_(8)
        self._text_view.setTextContainerInset_(AppKit.NSMakeSize(4, 8))

        scroll = AppKit.NSScrollView.alloc().initWithFrame_(
            make_rect(PADDING, text_y, text_w, text_h)
        )
        scroll.setDocumentView_(self._text_view)
        scroll.setHasVerticalScroller_(True)
        scroll.setBackgroundColor_(AppKit.NSColor.clearColor())
        scroll.setDrawsBackground_(False)
        scroll.verticalScroller().setAlphaValue_(0.2)
        content.addSubview_(scroll)

        # Champ de saisie
        input_y = PADDING + STATUS_H + 8
        self._input = AppKit.NSTextField.alloc().initWithFrame_(
            make_rect(PADDING, input_y, WINDOW_W - PADDING * 2 - 46, INPUT_H)
        )
        self._input.setPlaceholderString_("Votre message…")
        self._input.setBezeled_(True)
        self._input.setBezelStyle_(AppKit.NSTextFieldRoundedBezel)
        self._input.setBackgroundColor_(ns_white(0.15, 0.3))
        self._input.setTextColor_(ns_white(0.95, 0.9))
        self._input.setFont_(AppKit.NSFont.systemFontOfSize_(13))
        self._input.setEditable_(True)
        self._input.setSelectable_(True)
        self._input.setTarget_(self)
        self._input.setAction_('sendQuery:')
        content.addSubview_(self._input)

        # Bouton d'envoi
        btn_x = WINDOW_W - PADDING - 38
        self._send_btn = AppKit.NSButton.alloc().initWithFrame_(
            make_rect(btn_x, input_y, 38, INPUT_H)
        )
        self._send_btn.setBezelStyle_(AppKit.NSRoundedBezelStyle)
        self._send_btn.setTitle_("↗")
        self._send_btn.setFont_(
            AppKit.NSFont.systemFontOfSize_weight_(16, AppKit.NSFontWeightLight)
        )
        self._send_btn.setTarget_(self)
        self._send_btn.setAction_('sendQuery:')
        attr_title = AppKit.NSAttributedString.alloc().initWithString_attributes_(
            "↗", {AppKit.NSForegroundColorAttributeName: ns_white(0.8, 0.7)}
        )
        self._send_btn.setAttributedTitle_(attr_title)
        content.addSubview_(self._send_btn)

        # Indicateur de statut (point)
        self._status = AppKit.NSTextField.alloc().initWithFrame_(
            make_rect(PADDING, PADDING, 20, STATUS_H)
        )
        self._status.setStringValue_("●")
        self._status.setEditable_(False)
        self._status.setBezeled_(False)
        self._status.setDrawsBackground_(False)
        self._status.setFont_(AppKit.NSFont.systemFontOfSize_(12))
        self._status.setTextColor_(ns_color(0.2, 0.9, 0.4, 0.9))
        content.addSubview_(self._status)

        self._status_text = AppKit.NSTextField.alloc().initWithFrame_(
            make_rect(PADDING + 22, PADDING, 150, STATUS_H)
        )
        self._status_text.setStringValue_("Prêt")
        self._status_text.setEditable_(False)
        self._status_text.setBezeled_(False)
        self._status_text.setDrawsBackground_(False)
        self._status_text.setFont_(AppKit.NSFont.systemFontOfSize_(10))
        self._status_text.setTextColor_(ns_white(0.7, 0.8))
        content.addSubview_(self._status_text)

        # Démarrer la surveillance de la frappe
        self._start_typing_monitor()

    def _setup_space_observer(self):
        nc = AppKit.NSWorkspace.sharedWorkspace().notificationCenter()
        nc.addObserver_selector_name_object_(
            self,
            'spaceDidChange:',
            AppKit.NSWorkspaceActiveSpaceDidChangeNotification,
            None
        )
        print("👂 Observateur d'espace configuré")

    def spaceDidChange_(self, notification):
        print("🔄 Changement d'espace")
        self.orderFrontRegardless()
        self.setLevel_(Quartz.kCGFloatingWindowLevel + 1)

    def _setup_watchdog(self):
        self._watchdog = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            2.0, self, 'watchdogTick:', None, True
        )
        AppKit.NSRunLoop.currentRunLoop().addTimer_forMode_(
            self._watchdog, AppKit.NSRunLoopCommonModes
        )
        print("🐶 Watchdog activé (2s)")

    def watchdogTick_(self, timer):
        if self._is_dragging or self._is_processing:
            return
        if not self.isVisible():
            self.setHidden_(False)
        self.setLevel_(Quartz.kCGFloatingWindowLevel + 1)
        self.orderFrontRegardless()

    # -------------------------------------------------------------
    # Surveillance de la frappe
    # -------------------------------------------------------------
    def _start_typing_monitor(self):
        """Lance un timer qui surveille le contenu du champ de saisie toutes les 0.5s."""
        self._typing_timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.5, self, 'typingTimerFired:', None, True
        )
        # Forcer un premier appel
        self.typingTimerFired_(None)

    @objc.IBAction
    def typingTimerFired_(self, timer):
        """Appelé par le timer toutes les 0.5s."""
        current = self._input.stringValue()
        if current != self._last_text:
            self._last_text = current
            # Envoyer le texte partiel au prédicteur dans un thread séparé
            if hasattr(self, 'engine') and self.engine and hasattr(self.engine, 'predictor'):
                threading.Thread(target=self._send_to_predictor, args=(current,), daemon=True).start()

    def _send_to_predictor(self, text: str):
        """Envoie le texte partiel au service de prédiction de l'engine."""
        try:
            self.engine.predictor.update_partial_input(text)
        except Exception as e:
            # Silencieux pour ne pas perturber l'utilisateur
            pass

    # -------------------------------------------------------------
    # Envoi de la requête
    # -------------------------------------------------------------
    @objc.IBAction
    def sendQuery_(self, sender):
        print("🚀 sendQuery_ appelée")
        if self._is_processing:
            print("⚠️ Requête déjà en cours, ignorée")
            return
        query = self._input.stringValue().strip()
        print(f"Requête: '{query}'")
        if not query:
            print("⚠️ Requête vide, ignorée")
            return
        self._input.setStringValue_("")
        self._is_processing = True
        self._processing_start_time = time.time()
        print("📝 Appel de append_message_safe pour utilisateur")
        self.append_message_safe("Toi", query, user=True)

        # Mise à jour de l'UI : point orange, message "Réflexion..." et indicateur qui pulse
        self._set_status("●", ns_color(1.0, 0.6, 0.0), "Réflexion…")
        self._send_btn.setEnabled_(False)
        self._thinking_indicator.startAnimating()
        self._thinking_label.setStringValue_("En cours de réflexion")
        self._thinking_label.setAlphaValue_(1.0)

        print("🚀 Lancement du thread pour _process_query")
        threading.Thread(target=self._process_query, args=(query,), daemon=True).start()

    def _process_query(self, query):
        print(f"🧵 Thread _process_query démarré pour: '{query}'")
        try:
            # Afficher un message de début de réflexion
            AppHelper.callAfter(self.append_message_safe, "Agent", "Je réfléchis...", False)
            time.sleep(0.5)

            print("Appel de self.engine.process...")
            response, latency = self.engine.process(query, use_rag=True)
            print(f"✅ Réponse reçue: '{str(response)[:100]}…', latence={latency:.2f}s")

            if not response or not str(response).strip():
                response = "(Aucune réponse générée)"
                print("⚠️ Réponse vide, message par défaut utilisé")

            # Afficher la réponse dans le HUD
            AppHelper.callAfter(self.append_message_safe, "Agent", response, False)

            # Si la réponse indique une action, on peut ajouter un message contextuel
            if "✅ Application" in response:
                AppHelper.callAfter(self.append_message_safe, "Agent", "L'application est maintenant ouverte. Je peux taper du texte si vous le souhaitez.", False)
            elif "✅ Texte tapé" in response:
                AppHelper.callAfter(self.append_message_safe, "Agent", "Le texte a été saisi avec succès.", False)

            # Finaliser l'interface
            AppHelper.callAfter(self._on_response_ui_ready, latency)

        except Exception as e:
            print(f"❌ Exception dans _process_query: {e}")
            import traceback
            traceback.print_exc()
            AppHelper.callAfter(self._on_response, f"Erreur : {e}", None)

    @objc.python_method
    def _on_response(self, text, latency):
        # Cette méthode est conservée pour compatibilité, mais on utilise maintenant _on_response_ui_ready
        self.append_message_safe("IA", text, user=False)
        self._thinking_indicator.stopAnimating()
        self._thinking_label.setAlphaValue_(0.0)

        if latency is not None:
            self._latency_label.setStringValue_(f"{latency:.2f}s")
            self._set_status("●", ns_color(0.2, 0.9, 0.4), "Prêt")
        else:
            self._set_status("●", ns_color(1.0, 0.2, 0.2), "Erreur")
        self._send_btn.setEnabled_(True)
        self._is_processing = False
        self._is_dragging = False
        print("✅ _on_response terminé")

    @objc.python_method
    def _on_response_ui_ready(self, latency):
        """Met à jour l'interface après la réponse."""
        self._thinking_indicator.stopAnimating()
        self._thinking_label.setAlphaValue_(0.0)
        if latency is not None:
            self._latency_label.setStringValue_(f"{latency:.2f}s")
            self._set_status("●", ns_color(0.2, 0.9, 0.4), "Prêt")
        else:
            self._set_status("●", ns_color(1.0, 0.2, 0.2), "Erreur")
        self._send_btn.setEnabled_(True)
        self._is_processing = False
        self._is_dragging = False
        print("✅ Interface prête")

    @objc.python_method
    def append_message_safe(self, sender, text, user=True):
        """Ajoute un message en garantissant l'exécution sur le main thread."""
        import threading
        if threading.current_thread().name != "MainThread":
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                self._append_message_on_main,
                (sender, text, user),
                False
            )
        else:
            self._append_message_on_main((sender, text, user))

    @objc.python_method
    def _append_message_on_main(self, args):
        """Réelle mise à jour du NSTextView (exécutée sur main thread)."""
        sender, text, user = args
        print(f"📝 _append_message_on_main: {sender} -> '{text[:60]}…'")
        storage = self._text_view.textStorage()
        current = self._text_view.string()
        prefix = "\n" if current else ""
        sender_attrs = {
            AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_weight_(
                11, AppKit.NSFontWeightLight
            ),
            AppKit.NSForegroundColorAttributeName: (
                ns_color(0.6, 0.8, 1.0, 0.9) if user
                else ns_color(0.7, 1.0, 0.7, 0.9)
            ),
        }
        msg_attrs = {
            AppKit.NSFontAttributeName: AppKit.NSFont.systemFontOfSize_(12),
            AppKit.NSForegroundColorAttributeName: ns_white(0.92, 0.9),
        }
        full = AppKit.NSMutableAttributedString.alloc().init()
        full.appendAttributedString_(
            AppKit.NSAttributedString.alloc().initWithString_attributes_(
                f"{prefix}{sender}\n", sender_attrs
            )
        )
        full.appendAttributedString_(
            AppKit.NSAttributedString.alloc().initWithString_attributes_(
                f"{text}\n", msg_attrs
            )
        )
        storage.appendAttributedString_(full)
        self._text_view.setNeedsDisplay_(True)
        self._text_view.displayIfNeeded()
        end = len(self._text_view.string())
        self._text_view.scrollRangeToVisible_(Foundation.NSMakeRange(end, 0))
        scrollView = self._text_view.enclosingScrollView()
        if scrollView:
            scrollView.setNeedsDisplay_(True)
            scrollView.displayIfNeeded()
        print(f"   ✅ Message ajouté, total caractères: {end}")

    @objc.python_method
    def _set_status(self, dot, color, label):
        self._status.setStringValue_(dot)
        self._status.setTextColor_(color)
        self._status_text.setStringValue_(label)

    def close(self):
        if hasattr(self, '_watchdog') and self._watchdog:
            self._watchdog.invalidate()
        if hasattr(self, '_typing_timer') and self._typing_timer:
            self._typing_timer.invalidate()
        nc = AppKit.NSWorkspace.sharedWorkspace().notificationCenter()
        nc.removeObserver_(self)
        objc.super(HUDWindow, self).close()

class AppDelegate(AppKit.NSObject):
    def applicationDidFinishLaunching_(self, notification):
        print("🚀 Application lancée")
        try:
            self.config = Config()
            print("✅ Config chargée")

            self.engine = LucidEngine(self.config)
            print("✅ Engine initialisé")

            self.window = HUDWindow.alloc().init()
            self.window.engine = self.engine
            print("✅ Fenêtre créée, engine injecté")

            self.window.makeKeyAndOrderFront_(None)
            self.window.orderFrontRegardless()
            self.window.display()

            if hasattr(self.window, '_input'):
                self.window.makeFirstResponder_(self.window._input)
                print("🎯 Focus donné au champ de saisie")
            else:
                print("⚠️ _input introuvable")

            centre = AppKit.NSUserNotificationCenter.defaultUserNotificationCenter()
            centre.setDelegate_(self)
            print("🔔 Délégué des notifications configuré")

            print("✅ HUD prêt")
        except Exception as e:
            print(f"❌ Erreur initialisation : {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

    def userNotificationCenter_didActivateNotification_(self, center, notification):
        user_info = notification.userInfo()
        if user_info and user_info.get("action") == "open_file":
            filepath = user_info.get("filepath")
            if filepath and os.path.exists(filepath):
                subprocess.run(['open', filepath])
                print(f"📂 Ouverture du fichier : {filepath}")
            else:
                print(f"⚠️ Fichier introuvable : {filepath}")

    def applicationWillTerminate_(self, notification):
        print("👋 Arrêt de l'application")
        if hasattr(self, 'engine'):
            self.engine.stop()

def run_hud():
    print("🚀 Lancement de run_hud")
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)

    print("✅ Démarrage du runloop")
    AppHelper.runEventLoop()

if __name__ == "__main__":
    run_hud()