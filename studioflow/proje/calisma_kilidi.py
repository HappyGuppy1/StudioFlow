"""Tek çalışan proje ve durdurma isteği.

Aynı anda yalnızca bir proje çalışır: durdurma bayrağı tek olduğu için iki çalışma
birbirinin durdurma isteğini yer; ayrıca aynı metne iki akış yazarsa kayıt bozulur.
"""
import threading


class CalismaKilidi:
    """Durdurma bayrağı (`iptal`) ve çalışan projenin kaydı (`kayit["slug"]`)."""

    def __init__(self):
        self.iptal = threading.Event()
        self.kayit = {"slug": ""}

    def durdur(self):
        """Çalışan projeyi geçerli adımın sonunda durdur."""
        self.iptal.set()
        return "Durdurma istendi. Geçerli adım bitince proje kaydedilip duracak."

    def calisan(self):
        """Şu anda çalışan projenin klasör adı (yoksa boş metin)."""
        return self.kayit["slug"]


# Uygulamanın paylaşılan kilidi; eski adlar aynı nesnelere bağlıdır.
VARSAYILAN = CalismaKilidi()
IPTAL = VARSAYILAN.iptal
CALISAN = VARSAYILAN.kayit
durdur = VARSAYILAN.durdur
calisan = VARSAYILAN.calisan
