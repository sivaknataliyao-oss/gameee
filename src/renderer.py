"""Рендер видео из сценария + аудио + изображений.

Создаёт видео в стиле "новостной канал":
- Картинки с плавными переходами
- Текстовые оверлеи (субтитры + заголовки секций)
- Нижняя плашка с названием канала
- Ken Burns эффект (медленный зум/pan на картинках)
"""

import os
import subprocess
import json
from pathlib import Path


def get_audio_duration(audio_path: str) -> float:
    """Получает длительность аудио через ffprobe."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", audio_path],
        capture_output=True, text=True,
    )
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def render_video(
    script: dict,
    audio_path: str,
    image_paths: list[str],
    output_path: str,
    resolution: tuple[int, int] = (1920, 1080),
) -> str:
    """Рендерит финальное видео из компонентов.

    Подход: создаём слайдшоу из изображений, синхронизированное с аудио,
    добавляем текстовые оверлеи (заголовки секций).
    """
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    w, h = resolution

    audio_duration = get_audio_duration(audio_path)
    sections = script.get("sections", [])

    # Если нет изображений — создаём текстовые слайды
    if not image_paths:
        from .assets import create_text_slide
        run_dir = os.path.dirname(output_path)
        slides_dir = os.path.join(run_dir, "slides")
        os.makedirs(slides_dir, exist_ok=True)
        image_paths = []
        for i, section in enumerate(sections):
            slide_path = os.path.join(slides_dir, f"slide_{i:03d}.png")
            create_text_slide(section.get("heading", ""), slide_path, w, h)
            image_paths.append(slide_path)

    # Длительность каждой картинки
    n_images = len(image_paths)
    if n_images == 0:
        raise ValueError("Нет изображений для рендера")

    duration_per_image = audio_duration / n_images

    # Генерируем slideshow с crossfade через FFmpeg
    filter_parts = []
    inputs = []

    for i, img_path in enumerate(image_paths):
        inputs.extend(["-loop", "1", "-t", str(duration_per_image), "-i", img_path])

        # Scale + pad для единого разрешения, Ken Burns зум
        zoom = f"scale={w*2}:{h*2},zoompan=z='min(zoom+0.0005,1.2)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={int(duration_per_image*25)}:s={w}x{h}:fps=25"
        filter_parts.append(f"[{i}:v]{zoom}[v{i}]")

    # Concat все видеопотоки
    concat_inputs = "".join(f"[v{i}]" for i in range(n_images))
    filter_parts.append(f"{concat_inputs}concat=n={n_images}:v=1:a=0[slideshow]")

    # Добавляем заголовки секций как текстовые оверлеи
    overlay = "[slideshow]"
    current_time = 0
    for i, section in enumerate(sections):
        heading = section.get("heading", "").replace("'", "\\'").replace(":", "\\:")
        if heading:
            start = current_time
            end = start + duration_per_image * max(1, len(section.get("visuals", ["x"])))
            if end > audio_duration:
                end = audio_duration

            # Заголовок секции — белый текст на полупрозрачной плашке
            filter_parts.append(
                f"{overlay}"
                f"drawbox=x=0:y=ih-120:w=iw:h=120:color=black@0.6:t=fill,"
                f"drawtext=text='{heading}'"
                f":fontsize=42:fontcolor=white"
                f":x=(w-text_w)/2:y=h-85"
                f":enable='between(t,{start:.1f},{min(start + 5, end):.1f})'"
                f"[ovr{i}]"
            )
            overlay = f"[ovr{i}]"

        current_time += duration_per_image * max(1, len(section.get("visuals", ["x"])))

    # Финальный граф
    filter_complex = ";\n".join(filter_parts)

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-i", audio_path,
        "-filter_complex", filter_complex,
        "-map", f"{overlay.strip('[]')}",
        "-map", f"{n_images}:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        "-pix_fmt", "yuv420p",
        output_path,
    ]

    print(f"[RENDERER] Рендер видео ({audio_duration:.0f} сек, {n_images} изображений)...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"[RENDERER] ⚠ FFmpeg ошибка, пробую простой режим...")
        return _render_simple(image_paths, audio_path, output_path, audio_duration, w, h)

    print(f"[RENDERER] Видео готово: {output_path}")
    return output_path


def _render_simple(
    image_paths: list[str],
    audio_path: str,
    output_path: str,
    audio_duration: float,
    w: int = 1920,
    h: int = 1080,
) -> str:
    """Простой fallback рендер — слайдшоу без эффектов."""
    n = len(image_paths)
    duration_each = audio_duration / n

    # Создаём list-файл для concat demuxer
    list_file = output_path + ".imglist.txt"
    with open(list_file, "w") as f:
        for img in image_paths:
            f.write(f"file '{os.path.abspath(img)}'\n")
            f.write(f"duration {duration_each}\n")
        # Последний кадр нужно повторить для concat
        f.write(f"file '{os.path.abspath(image_paths[-1])}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", list_file,
        "-i", audio_path,
        "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black",
        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        "-pix_fmt", "yuv420p",
        output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    os.remove(list_file)

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg fallback тоже упал:\n{result.stderr[:500]}")

    print(f"[RENDERER] Видео готово (простой режим): {output_path}")
    return output_path
