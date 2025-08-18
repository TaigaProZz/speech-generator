import tkinter as tk
from tkinter import messagebox, filedialog, ttk
import numpy
import pygame

import os
import re
import tempfile
import shutil
import time
import atexit
import threading
from pathlib import Path
from typing import Optional
from elevenlabs.client import ElevenLabs


class TTSApplication:
    """Application Text-to-Speech avec interface Tkinter et ElevenLabs API"""
    
    def __init__(self):
        # Configuration des fichiers
        self.API_KEY_FILE = "apikey.txt"
        self.SAVE_FOLDER_FILE = "savepath.txt"
        self.CONFIG_DIR = Path.home() / ".tts_app"
        self.CONFIG_DIR.mkdir(exist_ok=True)
        
        # Dossier temporaire dédié
        self.app_temp_dir = Path(tempfile.gettempdir()) / "tts_app_temp"
        self.app_temp_dir.mkdir(exist_ok=True)
        
        # Variables d'état
        self.current_audio_file: Optional[Path] = None
        self.temp_audio_file: Optional[Path] = None
        self.audio_data: Optional[bytes] = None  # Stockage des données audio
        self.last_text = ""
        self.save_folder = self.load_save_folder()
        self.is_generating = False
        
        # Initialisation pygame
        pygame.mixer.init()
        
        # Configuration de l'interface
        self.setup_ui()
        self.load_saved_data()
        
        # Nettoyage initial
        self.clean_temp_dir()
        
        # Configuration du nettoyage à la fermeture
        atexit.register(self.cleanup)
    
    def setup_ui(self):
        """Configure l'interface utilisateur"""
        self.root = tk.Tk()
        self.root.title("Text to Speech - ElevenLabs")
        self.root.geometry("700x600")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Style
        style = ttk.Style()
        style.theme_use('clam')
        
        # Frame principal
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Section API Key
        api_frame = ttk.LabelFrame(main_frame, text="Configuration", padding="10")
        api_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(api_frame, text="API Key ElevenLabs:").pack(anchor=tk.W)
        self.api_key_var = tk.StringVar()
        self.api_key_entry = ttk.Entry(api_frame, textvariable=self.api_key_var, 
                                      show="*", width=50)
        self.api_key_entry.pack(fill=tk.X, pady=(5, 0))
        
        # Section Texte
        text_frame = ttk.LabelFrame(main_frame, text="Texte à convertir", padding="10")
        text_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Frame pour le texte et scrollbar
        text_container = ttk.Frame(text_frame)
        text_container.pack(fill=tk.BOTH, expand=True)
        
        self.text_entry = tk.Text(text_container, height=8, wrap=tk.WORD, font=('Arial', 10))
        scrollbar = ttk.Scrollbar(text_container, orient=tk.VERTICAL, command=self.text_entry.yview)
        self.text_entry.configure(yscrollcommand=scrollbar.set)
        
        self.text_entry.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Bind pour détecter les changements
        self.text_entry.bind("<<Modified>>", self.on_text_change)
        self.text_entry.bind("<KeyRelease>", self.update_char_count)
        
        # Compteur de caractères
        self.char_count_label = ttk.Label(text_frame, text="Caractères: 0")
        self.char_count_label.pack(anchor=tk.E, pady=(5, 0))
        
        # Section Dossier de sauvegarde
        folder_frame = ttk.LabelFrame(main_frame, text="Sauvegarde", padding="10")
        folder_frame.pack(fill=tk.X, pady=(0, 10))
        
        folder_btn_frame = ttk.Frame(folder_frame)
        folder_btn_frame.pack(fill=tk.X)
        
        ttk.Button(folder_btn_frame, text="Choisir dossier", 
                  command=self.select_folder).pack(side=tk.LEFT)
        
        self.folder_label = ttk.Label(folder_frame, text=f"Dossier: {self.save_folder}")
        self.folder_label.pack(anchor=tk.W, pady=(5, 0))
        
        # Section Contrôles
        controls_frame = ttk.LabelFrame(main_frame, text="Contrôles", padding="10")
        controls_frame.pack(fill=tk.X)
        
        # Frame pour les boutons principaux
        btn_frame = ttk.Frame(controls_frame)
        btn_frame.pack(fill=tk.X)
        
        # Boutons principaux
        self.generate_btn = ttk.Button(btn_frame, text="Générer et lire l'audio", 
                                      command=self.generate_audio_threaded)
        self.generate_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        self.play_btn = ttk.Button(btn_frame, text="Rejouer", 
                                  command=self.replay_audio)
        
        self.download_btn = ttk.Button(btn_frame, text="Télécharger", 
                                      command=self.download_audio)
        
        self.stop_btn = ttk.Button(btn_frame, text="Arrêter", 
                                  command=self.stop_audio)
        self.stop_btn.pack(side=tk.LEFT, padx=(5, 5))
        
        self.reset_btn = ttk.Button(btn_frame, text="Réinitialiser", 
                                   command=self.reset_state)
        self.reset_btn.pack(side=tk.RIGHT)
        
        # Barre de progression
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(controls_frame, variable=self.progress_var, 
                                           mode='indeterminate')
        
        # Status bar
        self.status_var = tk.StringVar(value="Prêt")
        status_bar = ttk.Label(main_frame, textvariable=self.status_var, 
                              relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(fill=tk.X, pady=(10, 0))
        
        self.update_ui_state()
    
    def load_saved_data(self):
        """Charge les données sauvegardées"""
        api_key = self.load_api_key()
        if api_key:
            self.api_key_var.set(api_key)
    
    def update_char_count(self, event=None):
        """Met à jour le compteur de caractères"""
        text = self.text_entry.get("1.0", tk.END).strip()
        count = len(text)
        self.char_count_label.config(text=f"Caractères: {count}")
        
        # Avertissement si texte trop long
        if count > 5000:
            self.char_count_label.config(foreground="red")
        elif count > 2500:
            self.char_count_label.config(foreground="orange")
        else:
            self.char_count_label.config(foreground="black")
    
    def save_save_folder(self, path: str):
        """Sauvegarde le chemin du dossier de sauvegarde"""
        config_file = self.CONFIG_DIR / self.SAVE_FOLDER_FILE
        config_file.write_text(path, encoding="utf-8")
    
    def load_save_folder(self) -> str:
        """Charge le chemin du dossier de sauvegarde"""
        config_file = self.CONFIG_DIR / self.SAVE_FOLDER_FILE
        if config_file.exists():
            return config_file.read_text(encoding="utf-8").strip()
        return str(Path.home() / "Downloads")
    
    def save_api_key(self, api_key: str):
        """Sauvegarde la clé API"""
        config_file = self.CONFIG_DIR / self.API_KEY_FILE
        config_file.write_text(api_key, encoding="utf-8")
    
    def load_api_key(self) -> str:
        """Charge la clé API"""
        config_file = self.CONFIG_DIR / self.API_KEY_FILE
        if config_file.exists():
            return config_file.read_text(encoding="utf-8").strip()
        return ""
    
    def stop_audio(self):
        """Arrête la lecture audio et libère les ressources"""
        try:
            if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
            
            # Décharge le fichier audio pour libérer le handle
            if pygame.mixer.get_init():
                pygame.mixer.music.unload()
        except:
            pass
        
        self.current_audio_file = None
        time.sleep(0.1)  # Attendre que pygame libère le fichier
    
    def clean_temp_dir(self):
        """Nettoie le dossier temporaire"""
        # Seulement arrêter l'audio si pygame est initialisé
        if pygame.mixer.get_init():
            self.stop_audio()
        
        try:
            for file_path in self.app_temp_dir.glob("*"):
                if file_path.is_file():
                    try:
                        file_path.unlink()
                    except PermissionError:
                        # Le fichier est encore utilisé, on essaiera plus tard
                        pass
        except Exception as e:
            print(f"Erreur lors du nettoyage: {e}")
    
    def create_temp_audio_file(self) -> Path:
        """Crée un fichier temporaire avec un nom unique"""
        import uuid
        filename = f"temp_audio_{uuid.uuid4().hex[:8]}.mp3"
        return self.app_temp_dir / filename
    
    def play_audio(self, filename: Path):
        """Lit un fichier audio"""
        if not filename or not filename.exists():
            return False
        
        try:
            # Vérifier que pygame mixer est initialisé
            
            self.stop_audio()
            self.current_audio_file = filename
            pygame.mixer.music.load(str(filename))
            pygame.mixer.music.play()
            self.status_var.set("Lecture en cours...")
            return True
        except Exception as e:
            messagebox.showerror("Erreur de lecture", f"Impossible de lire l'audio: {e}")
            return False
    
    def replay_audio(self):
        """Rejoue le dernier audio généré"""
        if self.audio_data:
            # Créer un nouveau fichier temporaire pour la lecture
            temp_file = self.create_temp_audio_file()
            temp_file.write_bytes(self.audio_data)
            self.play_audio(temp_file)
        else:
            messagebox.showwarning("Aucun audio", "Aucun fichier audio à rejouer.")
    
    def sanitize_filename(self, text: str) -> str:
        """Nettoie le nom de fichier"""
        # Supprime les caractères interdits
        filename = re.sub(r'[\\/*?:"<>|]', "_", text)
        # Limite la longueur et supprime les espaces en trop
        filename = filename.strip()[:50]
        return filename if filename else "audio"
    
    def select_folder(self):
        """Sélectionne le dossier de sauvegarde"""
        folder = filedialog.askdirectory(initialdir=self.save_folder)
        if folder:
            self.save_folder = folder
            self.save_save_folder(self.save_folder)
            self.folder_label.config(text=f"Dossier: {self.save_folder}")
    
    def generate_audio_file(self, text: str = None) -> bool:
        """Génère le fichier audio"""
        if text is None:
            text = self.text_entry.get("1.0", tk.END).strip()
        
        api_key = self.api_key_var.get().strip()
        
        # Validations
        if not api_key:
            messagebox.showerror("Erreur", "Veuillez entrer votre API Key.")
            return False
        
        if not text:
            messagebox.showerror("Erreur", "Veuillez entrer un texte.")
            return False
        
        if len(text) > 10000:
            if not messagebox.askyesno("Texte long", 
                                     "Le texte est très long. Continuer ?"):
                return False
        
        try:
            self.status_var.set("Génération de l'audio...")
            self.save_api_key(api_key)
            
            # Initialisation du client ElevenLabs
            elevenlabs = ElevenLabs(api_key=api_key)
            
            # Génération de l'audio
            audio_generator = elevenlabs.text_to_speech.convert(
                text=text,
                voice_id="pNInz6obpgDQGcFmaJgB",  # Adam voice
                model_id="eleven_multilingual_v2",
                output_format="mp3_44100_128",
            )
            
            # Collecte des chunks audio
            audio_chunks = []
            for chunk in audio_generator:
                audio_chunks.append(chunk)
            
            # Stockage des données audio en mémoire
            self.audio_data = b"".join(audio_chunks)
            
            # Création d'un fichier temporaire pour la lecture
            self.temp_audio_file = self.create_temp_audio_file()
            self.temp_audio_file.write_bytes(self.audio_data)
            
            self.last_text = text
            self.status_var.set("Audio généré avec succès")
            return True
            
        except Exception as e:
            error_msg = f"Erreur lors de la génération: {str(e)}"
            messagebox.showerror("Erreur", error_msg)
            self.status_var.set("Erreur de génération")
            return False
    
    def generate_audio_threaded(self):
        """Lance la génération audio dans un thread séparé"""
        if self.is_generating:
            return
        
        self.is_generating = True
        self.update_ui_state()
        self.progress_bar.pack(fill=tk.X, pady=(10, 0))
        self.progress_bar.start(10)
        
        def generate_thread():
            success = self.generate_audio_file()
            
            # Mise à jour de l'UI dans le thread principal
            self.root.after(0, lambda: self.on_generation_complete(success))
        
        thread = threading.Thread(target=generate_thread, daemon=True)
        thread.start()
    
    def on_generation_complete(self, success: bool):
        """Callback appelé après la génération"""
        self.is_generating = False
        self.progress_bar.stop()
        self.progress_bar.pack_forget()
        
        if success:
            self.play_audio(self.temp_audio_file)
            
        self.update_ui_state()
    
    def download_audio(self):
        """Télécharge/sauvegarde le fichier audio"""
        if not self.audio_data:
            messagebox.showerror("Erreur", "Aucun fichier audio à télécharger.")
            return
        
        try:
            # Arrêter la lecture pour libérer le fichier
            self.stop_audio()
            
            # Génération du nom de fichier
            filename = self.sanitize_filename(self.last_text)
            save_path = Path(self.save_folder) / f"{filename}.mp3"
            
            # Gestion des doublons
            counter = 1
            original_path = save_path
            while save_path.exists():
                save_path = original_path.parent / f"{original_path.stem}_{counter}.mp3"
                counter += 1
            
            # Écriture directe des données audio
            save_path.write_bytes(self.audio_data)
            
            messagebox.showinfo("Téléchargé", 
                              f"Fichier audio sauvegardé:\n{save_path}")
            self.status_var.set(f"Fichier sauvegardé: {save_path.name}")
            
        except Exception as e:
            messagebox.showerror("Erreur", 
                               f"Impossible de sauvegarder le fichier:\n{e}")
    
    def update_ui_state(self):
        """Met à jour l'état des boutons selon le contexte"""
        has_audio_data = self.audio_data is not None
        
        # Boutons conditionnels
        if has_audio_data and not self.is_generating:
            self.play_btn.pack(side=tk.LEFT, padx=(5, 5))
            self.download_btn.pack(side=tk.LEFT, padx=(5, 5))
        else:
            self.play_btn.pack_forget()
            self.download_btn.pack_forget()
        
        # État du bouton générer
        self.generate_btn.configure(
            state='disabled' if self.is_generating else 'normal',
            text="Génération..." if self.is_generating else "Générer et lire l'audio"
        )
    
    def on_text_change(self, event=None):
        """Détecte les changements dans le texte"""
        if hasattr(self, 'text_entry') and self.text_entry.edit_modified():
            self.update_ui_state()
            self.text_entry.edit_modified(False)
            self.update_char_count()
    
    def reset_state(self):
        """Remet l'application à l'état initial"""
        self.stop_audio()
        
        # Nettoyage des données audio
        self.audio_data = None
        
        # Nettoyage du fichier temporaire
        if self.temp_audio_file and self.temp_audio_file.exists():
            try:
                self.temp_audio_file.unlink()
            except Exception:
                pass
        
        self.temp_audio_file = None
        self.last_text = ""
        
        # Reset de l'interface
        self.text_entry.delete("1.0", tk.END)
        self.status_var.set("Prêt")
        self.update_ui_state()
        self.update_char_count()
    
    def cleanup(self):
        """Nettoyage général à la fermeture"""
        # Arrêter l'audio avant de quitter pygame
        if pygame.mixer.get_init():
            self.stop_audio()
            time.sleep(0.2)  # Attendre que pygame libère complètement les ressources
            pygame.mixer.quit()
        
        # Nettoyer les fichiers temporaires après avoir quitté pygame
        try:
            for file_path in self.app_temp_dir.glob("*"):
                if file_path.is_file():
                    try:
                        file_path.unlink()
                    except:
                        pass
        except Exception as e:
            print(f"Erreur lors du nettoyage final: {e}")
    
    def on_closing(self):
        """Gestionnaire de fermeture de fenêtre"""
        self.cleanup()
        self.root.destroy()
    
    def run(self):
        """Lance l'application"""
        self.root.mainloop()


def main():
    """Point d'entrée principal"""
    try:
        app = TTSApplication()
        app.run()
    except KeyboardInterrupt:
        print("Application interrompue par l'utilisateur")
    except Exception as e:
        print(f"Erreur fatale: {e}")


if __name__ == "__main__":
    main()