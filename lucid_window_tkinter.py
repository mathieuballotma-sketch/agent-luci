#!/usr/bin/env python3
# lucid_window_tkinter.py - Version diagnostic avec prints

import tkinter as tk
import threading
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from app.core.engine import LucidEngine
from app.core.config import Config

class LucidWindowTkinter:
    def __init__(self, engine):
        print("🟡 Initialisation de la fenêtre")
        self.engine = engine
        self.root = tk.Tk()
        print("✅ Tk() créé")
        self.root.title("")
        self.root.geometry("400x200+100+100")
        print("✅ Geometry set")
        self.root.overrideredirect(True)
        print("✅ overrideredirect")
        self.root.attributes('-alpha', 0.4)
        self.root.attributes('-topmost', True)
        print("✅ attributes set")
        
        self.root.bind('<Button-1>', self.start_move)
        self.root.bind('<B1-Motion>', self.on_move)
        
        self.x = 0
        self.y = 0
        
        self.bg_dark = '#1c1c1e'
        self.bg_darker = '#2c2c2e'
        self.bg_input = '#3a3a3c'
        self.accent = '#007aff'
        self.success = '#30d158'
        self.warning = '#ff9f0a'
        self.error = '#ff453a'
        
        print("🟡 Début setup_ui")
        self.setup_ui()
        print("✅ setup_ui terminé")
        self.display_message("Assistant", "Bonjour ! Test Tkinter. Change d'app pour voir si je reste.")
        print("✅ message affiché")
        
    def setup_ui(self):
        print("   🟡 Création du main_frame")
        main_frame = tk.Frame(self.root, bg=self.bg_dark)
        main_frame.pack(fill=tk.BOTH, expand=True)
        print("   ✅ main_frame packé")
        
        header = tk.Frame(main_frame, bg=self.bg_darker, height=30)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        print("   ✅ header packé")
        
        header.bind('<Button-1>', self.start_move)
        header.bind('<B1-Motion>', self.on_move)
        
        title = tk.Label(header, text="🤖 Agent Lucide (test)", bg=self.bg_darker, fg='white',
                         font=('SF Pro Display', 12, 'bold'))
        title.pack(side=tk.LEFT, padx=10)
        title.bind('<Button-1>', self.start_move)
        title.bind('<B1-Motion>', self.on_move)
        
        close_btn = tk.Button(header, text="✕", bg=self.bg_darker, fg='white',
                              font=('Arial', 10), bd=0, command=self.root.quit,
                              activebackground=self.error, activeforeground='white')
        close_btn.pack(side=tk.RIGHT, padx=10)
        print("   ✅ bouton fermer packé")
        
        self.chat = tk.Text(main_frame, bg=self.bg_dark, fg='white', wrap=tk.WORD,
                            font=('Arial', 10), bd=0, highlightthickness=0)
        self.chat.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        print("   ✅ chat packé")
        
        input_frame = tk.Frame(main_frame, bg=self.bg_input, height=40)
        input_frame.pack(fill=tk.X, padx=10, pady=(0,10))
        input_frame.pack_propagate(False)
        print("   ✅ input_frame packé")
        
        self.entry = tk.Entry(input_frame, bg=self.bg_input, fg='white',
                              font=('Arial', 10), bd=0, insertbackground='white')
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10, pady=10)
        self.entry.bind('<Return>', self.send_message)
        
        send_btn = tk.Button(input_frame, text="→", bg=self.accent, fg='white',
                            font=('Arial', 12, 'bold'), bd=0, width=3,
                            command=self.send_message)
        send_btn.pack(side=tk.RIGHT, padx=5)
        print("   ✅ entry et send_btn packés")
        
        self.status = tk.Label(main_frame, text="Prêt", bg=self.bg_dark,
                               fg=self.success, anchor='w')
        self.status.pack(fill=tk.X, padx=10, pady=(0,5))
        print("   ✅ status packé")
    
    def start_move(self, event):
        self.x = event.x
        self.y = event.y
    
    def on_move(self, event):
        deltax = event.x - self.x
        deltay = event.y - self.y
        x = self.root.winfo_x() + deltax
        y = self.root.winfo_y() + deltay
        self.root.geometry(f"+{x}+{y}")
    
    def display_message(self, sender, message):
        self.chat.insert(tk.END, f"{sender}: {message}\n\n")
        self.chat.see(tk.END)
        self.root.update()
    
    def send_message(self, event=None):
        query = self.entry.get().strip()
        if not query:
            return
        self.entry.delete(0, tk.END)
        self.display_message("Vous", query)
        self.status.config(text="Réflexion...", fg=self.warning)
        self.root.update()
        
        def process():
            try:
                response, latency = self.engine.process(query, use_rag=True)
                self.root.after(0, self.display_message, "Agent", response)
                self.root.after(0, lambda: self.status.config(text=f"Prêt ({latency:.2f}s)", fg=self.success))
            except Exception as e:
                self.root.after(0, self.display_message, "Agent", f"Erreur : {e}")
                self.root.after(0, lambda: self.status.config(text="Erreur", fg=self.error))
        
        threading.Thread(target=process, daemon=True).start()
    
    def run(self):
        print("🟢 Avant mainloop")
        # Forcer l'affichage
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        print("   Après deiconify/lift")
        self.root.mainloop()
        print("🔴 Après mainloop")

def main():
    print("🚀 Test Tkinter")
    cfg = Config.load("config.yaml")
    cfg.validate()
    engine = LucidEngine(cfg)
    window = LucidWindowTkinter(engine)
    print("🟡 Fenêtre créée, appel de run()")
    window.run()
    print("✅ run() terminé")

if __name__ == "__main__":
    main()