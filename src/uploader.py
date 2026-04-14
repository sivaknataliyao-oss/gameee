"""Загрузка видео на YouTube через Data API v3.

Первый запуск потребует OAuth авторизацию в браузере.
После этого token сохраняется локально.

Настройка:
1. Создай проект в Google Cloud Console
2. Включи YouTube Data API v3
3. Создай OAuth 2.0 credentials (Desktop app)
4. Скачай client_secret.json в корень проекта
"""

import os
import json
import pickle
from pathlib import Path


def upload_to_youtube(
    video_path: str,
    title: str,
    description: str,
    tags: list[str],
    thumbnail_path: str | None = None,
    category_id: str = "25",  # News & Politics
    privacy: str = "public",
    credentials_path: str = "client_secret.json",
    token_path: str = "youtube_token.pickle",
) -> dict:
    """Загружает видео на YouTube.

    Returns:
        dict с video_id и url загруженного видео.
    """
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        print("[UPLOAD] ⚠ Нужно: pip install google-api-python-client google-auth-oauthlib")
        return _save_upload_pending(video_path, title, description, tags)

    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

    # Авторизация
    creds = None
    if os.path.exists(token_path):
        with open(token_path, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(credentials_path):
                print(f"[UPLOAD] ⚠ Нет {credentials_path} — создай OAuth credentials в Google Cloud Console")
                return _save_upload_pending(video_path, title, description, tags)
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_path, "wb") as f:
            pickle.dump(creds, f)

    youtube = build("youtube", "v3", credentials=creds)

    # Загрузка
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags[:30],
            "categoryId": category_id,
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)

    print(f"[UPLOAD] Загружаю: {title[:60]}...")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"[UPLOAD] Прогресс: {int(status.progress() * 100)}%")

    video_id = response["id"]
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"[UPLOAD] Готово: {video_url}")

    # Устанавливаем thumbnail
    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path, mimetype="image/jpeg"),
            ).execute()
            print("[UPLOAD] Thumbnail установлен")
        except Exception as e:
            print(f"[UPLOAD] ⚠ Thumbnail не установлен: {e}")

    return {"video_id": video_id, "url": video_url}


def _save_upload_pending(video_path: str, title: str, description: str,
                         tags: list[str]) -> dict:
    """Сохраняет данные для ручной загрузки, если автозагрузка невозможна."""
    pending = {
        "status": "pending_manual_upload",
        "video_path": os.path.abspath(video_path),
        "title": title,
        "description": description,
        "tags": tags,
    }
    pending_path = video_path.replace(".mp4", "_upload_pending.json")
    with open(pending_path, "w", encoding="utf-8") as f:
        json.dump(pending, f, ensure_ascii=False, indent=2)
    print(f"[UPLOAD] Сохранено для ручной загрузки: {pending_path}")
    return pending
