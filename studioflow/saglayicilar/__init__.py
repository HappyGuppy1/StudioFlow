"""Dış servisler: video (Hugging Face), görsel (Cloudflare), ses (Edge/Gemini/Chatterbox),
metin yapay zekâsı (Gemini/OpenAI/Anthropic) ve hesap havuzu.

Bu katman Gradio'yu ve projeyi bilmez. Her sağlayıcı `taban` modülündeki soyut
sınıflardan birini uygular; yeni bir servis eklemek yeni bir sınıf + `kayit` satırıdır.
"""
