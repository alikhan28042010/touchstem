"""Printable A4 teacher sheet (PDF): preview, legend, QR to the audio guide, lesson and quiz with answers."""
from __future__ import annotations

import io
import textwrap

from .lesson import Lesson
from .quality import PrintEstimate, Report

L10N = {
    "ru": {"legend": "Обозначения", "qr": "Аудиогид для ученика:\nнаведите камеру телефона",
           "score": "Читаемость на ощупь: {s}/100", "print": "3D-печать: ≈{g:.0f} г пластика, ≈{c:.0f} ₸, ≈{m:.0f} мин",
           "lesson": "Урок по листу", "tour": "Маршрут пальца", "facts": "Что важно", "quiz": "Вопросы и ответы",
           "answer": "Ответ", "foot": "TouchSTEM · проверьте Брайль и названия с тифлопедагогом перед уроком"},
    "kk": {"legend": "Шартты белгілер", "qr": "Оқушыға арналған аудиогид:\nтелефон камерасын бағыттаңыз",
           "score": "Сипап оқуға ыңғайлылығы: {s}/100", "print": "3D-басып шығару: ≈{g:.0f} г пластик, ≈{c:.0f} ₸, ≈{m:.0f} мин",
           "lesson": "Парақ бойынша сабақ", "tour": "Саусақ жолы", "facts": "Маңыздысы", "quiz": "Сұрақтар мен жауаптар",
           "answer": "Жауабы", "foot": "TouchSTEM · сабақ алдында Брайль мен атауларды тифлопедагогпен тексеріңіз"},
}


def teacher_pdf(title: str, preview_png: bytes, legend_lines: list[str], lesson: Lesson, report: Report | None,
                estimate: PrintEstimate | None, qr_png: bytes | None, lang: str = "ru") -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from PIL import Image

    t = L10N[lang]
    ink, muted, accent = "#1b1f24", "#5b6470", "#2440c8"
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        # page 1
        fig = plt.figure(figsize=(8.27, 11.69))
        fig.text(0.07, 0.95, title or "TouchSTEM", fontsize=20, weight="bold", color=ink, family="DejaVu Sans")
        img = Image.open(io.BytesIO(preview_png))
        w, h = img.size
        box_w, box_h = 0.86, 0.52
        scale = min(box_w / w * 8.27, box_h / h * 11.69)
        iw, ih = w * scale / 8.27, h * scale / 11.69
        ax = fig.add_axes([0.07, 0.92 - ih, iw, ih])
        ax.imshow(img)
        ax.axis("off")
        y = 0.92 - ih - 0.04
        fig.text(0.07, y, t["legend"], fontsize=13, weight="bold", color=ink)
        y -= 0.028
        for line in legend_lines[1:] if legend_lines else []:
            fig.text(0.07, y, line, fontsize=10.5, color=ink)
            y -= 0.022
        if report:
            fig.text(0.07, 0.07, t["score"].format(s=report.score), fontsize=10, color=accent)
        if estimate:
            fig.text(0.07, 0.05, t["print"].format(g=estimate.grams, c=estimate.cost_tenge, m=estimate.minutes),
                     fontsize=10, color=muted)
        if qr_png:
            qa = fig.add_axes([0.73, 0.06, 0.2, 0.14])
            qa.imshow(Image.open(io.BytesIO(qr_png)), cmap="gray")
            qa.axis("off")
            fig.text(0.73, 0.215, t["qr"], fontsize=8.5, color=ink, va="bottom")
        fig.text(0.07, 0.02, t["foot"], fontsize=7.5, color=muted)
        pdf.savefig(fig)
        plt.close(fig)

        # page 2: lesson
        fig = plt.figure(figsize=(8.27, 11.69))
        y = 0.95
        fig.text(0.07, y, t["lesson"], fontsize=16, weight="bold", color=ink)
        y -= 0.04

        def para(text, size=10, color=ink, indent=0.07, width=84):
            nonlocal y
            for line in textwrap.wrap(text, width=width):
                fig.text(indent, y, line, fontsize=size, color=color)
                y -= 0.019 * size / 10
            y -= 0.006

        para(lesson.intro)
        for head, items in ((t["tour"], lesson.tour), (t["facts"], lesson.physics)):
            y -= 0.01
            fig.text(0.07, y, head, fontsize=12, weight="bold", color=ink)
            y -= 0.028
            for i, s in enumerate(items, 1):
                para(f"{i}. {s}", width=82)
        y -= 0.01
        fig.text(0.07, y, t["quiz"], fontsize=12, weight="bold", color=ink)
        y -= 0.028
        for q, a in lesson.quiz:
            para(q, width=82)
            para(f"{t['answer']}: {a}", color=accent, indent=0.1, width=78)
            if y < 0.06:
                break
        pdf.savefig(fig)
        plt.close(fig)
    return buf.getvalue()
