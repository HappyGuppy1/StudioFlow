"""Harita animasyonu: duraklar arasında kendini çizen rota ve haritada uçan kamera (MP4).

Belgesel / Vox tarzı harita sahneleri için: harita karoları ücretsiz kaynaklardan
indirilir ve önbelleğe alınır, kamera her karede hesaplanır (MapLibre'nin `flyTo`
eğrisi), rota ve durak etiketleri kare kare çizilir, kareler ffmpeg'e akıtılır.
Tarayıcı ya da API anahtarı gerekmez. Bu katman Gradio'yu bilmez.
"""
