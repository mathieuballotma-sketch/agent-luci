import os
import base64
import keyring
from cryptography.fernet import Fernet
from ..utils.logger import logger

SERVICE_NAME = "com.agentlucide.crypto"
KEYRING_USERNAME = "master_key"

class CryptoManager:
    def __init__(self):
        # On ne stocke pas de sel si on ne dérive pas d'un mot de passe
        self.key = self._get_or_create_key()
        self.cipher = Fernet(self.key)

    def _get_or_create_key(self) -> bytes:
        stored_key = keyring.get_password(SERVICE_NAME, KEYRING_USERNAME)
        
        if stored_key:
            # Fernet attend des bytes, keyring rend une string
            return stored_key.encode()
        else:
            # Générer une clé Fernet (déjà en base64 url-safe)
            new_key = Fernet.generate_key().decode()
            keyring.set_password(SERVICE_NAME, KEYRING_USERNAME, new_key)
            logger.info("🔐 Nouvelle clé de chiffrement maîtresse stockée dans le Trousseau macOS.")
            return new_key.encode()

    def encrypt(self, data: bytes) -> bytes:
        return self.cipher.encrypt(data)

    def decrypt(self, encrypted_data: bytes) -> bytes:
        try:
            return self.cipher.decrypt(encrypted_data)
        except Exception as e:
            logger.error(f"❌ Erreur de déchiffrement : {e}")
            raise

    # ... (garder tes méthodes file_encrypt/decrypt mais avec gestion d'erreurs)