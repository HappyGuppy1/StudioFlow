"""Sayfa tabanı: her sekme bileşenlerini paylaşılan ad alanına kurar ve olaylarını bağlar."""
from abc import ABC, abstractmethod
from types import SimpleNamespace


class Bilesenler(SimpleNamespace):
    """Bütün sayfaların bileşenlerini taşıyan ortak ad alanı (`b.pj_metin` gibi)."""


class Sayfa(ABC):
    ad = ""

    @abstractmethod
    def kur(self, b):
        """Bileşenleri oluştur; hepsi `b` üzerine yazılır (sayfalar arası erişim için)."""

    def bagla(self, b):
        """Olayları bağla. Kurulum bittikten sonra, bütün sayfalar için çağrılır."""
