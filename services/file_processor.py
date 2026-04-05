# -*- coding: utf-8 -*-
"""Image processing, PDF conversion, OCR"""

import os, uuid, base64
from PIL import Image, ImageFilter, ImageEnhance, ImageOps
Image.MAX_IMAGE_PIXELS = None  # Allow large questionnaire scans
from config import app, HAS_PYMUPDF, HAS_TESSERACT

# ========== 图片处理 ==========
def preprocess_image(image_path):
    try:
        img = Image.open(image_path)
        if img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')
        # Resize very large images to avoid API limits (max ~20M pixels)
        max_pixels = 20_000_000
        w, h = img.size
        total = w * h
        if total > max_pixels:
            ratio = (max_pixels / total) ** 0.5
            new_w = int(w * ratio)
            new_h = int(h * ratio)
            img = img.resize((new_w, new_h), Image.LANCZOS)
        gray = img.convert('L')
        gray = ImageOps.autocontrast(gray, cutoff=1)
        gray = gray.filter(ImageFilter.SHARPEN)
        enhancer = ImageEnhance.Contrast(gray)
        gray = enhancer.enhance(1.5)
        preprocessed_path = os.path.join(
            app.config['UPLOAD_FOLDER'],
            f"pre_{uuid.uuid4().hex[:8]}_{os.path.basename(image_path)}"
        )
        gray.save(preprocessed_path)
        return preprocessed_path
    except Exception:
        return image_path


def image_to_base64(image_path):
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode('utf-8')


def pdf_to_images(pdf_path):
    if not HAS_PYMUPDF:
        raise RuntimeError("PDF功能需要PyMuPDF库，请运行: pip install PyMuPDF")
    doc = fitz.open(pdf_path)
    image_paths = []
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat)
        img_path = os.path.join(
            app.config['UPLOAD_FOLDER'],
            f"pdf_page_{uuid.uuid4().hex[:8]}_{page_num}.png"
        )
        pix.save(img_path)
        image_paths.append(img_path)
    doc.close()
    return image_paths


# ========== 本地OCR引擎 ==========

def local_ocr(image_path):
    """使用Tesseract对单张图片进行本地OCR识别"""
    if not HAS_TESSERACT:
        raise RuntimeError("pytesseract 未安装，请运行: pip install pytesseract，并确保系统已安装 Tesseract-OCR")
    preprocessed_path = preprocess_image(image_path)
    try:
        img = Image.open(preprocessed_path)
        text = pytesseract.image_to_string(img, lang='chi_sim+eng', config='--psm 6')
        return text.strip()
    finally:
        if preprocessed_path != image_path and os.path.exists(preprocessed_path):
            try:
                os.remove(preprocessed_path)
            except Exception:
                pass


def local_ocr_pdf(pdf_path):
    """对PDF的每一页进行OCR识别，合并全部文本"""
    image_paths = pdf_to_images(pdf_path)
    all_text = []
    for img_path in image_paths:
        try:
            page_text = local_ocr(img_path)
            if page_text:
                all_text.append(page_text)
        finally:
            try:
                if os.path.exists(img_path):
                    os.remove(img_path)
            except Exception:
                pass
    return '\n\n'.join(all_text)


def _extract_pdf_text(pdf_path):
    """使用PyMuPDF提取PDF中的嵌入文本（数字PDF直接提取，无需OCR）"""
    if not HAS_PYMUPDF:
        return ''
    try:
        doc = fitz.open(pdf_path)
        text_parts = []
        for page in doc:
            text = page.get_text()
            if text and text.strip():
                text_parts.append(text.strip())
        doc.close()
        return '\n\n'.join(text_parts)
    except Exception:
        return ''

