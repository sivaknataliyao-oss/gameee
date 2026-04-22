"""Permission request templates (RU/EN). Used by manager to DM authors."""
from __future__ import annotations

RU_SHORT = """Привет! Я делаю короткие вертикальные видео (YouTube/TikTok) с озвучкой интересных историй.
Мне очень понравился ваш пост «{title}».

Можно ли получить ваше разрешение:
1) пересказать/сократить текст,
2) озвучить (TTS),
3) опубликовать с указанием авторства (ваш ник + ссылка на пост)?

Если да — просто ответьте «Да, разрешаю» и подскажите, как лучше вас указать.
Если нет — ок, не использую. Спасибо!"""

EN_SHORT = """Hi! I create short vertical videos (YouTube/TikTok) narrating compelling stories.
I loved your post “{title}”.

May I have your permission to:
1) edit/condense the text,
2) add voiceover (TTS),
3) publish it with attribution (your username + link to post)?

If yes — just reply “Yes, I give permission” and tell me how you want to be credited.
If not — no worries. Thank you!"""


def render(title: str, lang: str = "ru") -> str:
    t = RU_SHORT if lang == "ru" else EN_SHORT
    return t.format(title=title)
