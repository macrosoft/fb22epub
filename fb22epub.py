#!/usr/bin/env python3
"""
Конвертер FB2 в EPUB 3.
Зависимости: lxml, Pillow (опционально, для обработки изображений)
pip install lxml Pillow
"""
import os
import sys
import uuid
import zipfile
import base64
import mimetypes
import re
import struct
from io import BytesIO
from datetime import datetime, timezone
from xml.etree import ElementTree as ET
from pathlib import Path

try:
    from lxml import etree as lxml_etree
    USE_LXML = True
except ImportError:
    USE_LXML = False

# Пространства имён FB2
FB2_NS = 'http://www.gribuser.ru/xml/fictionbook/2.0'
XLINK_NS = 'http://www.w3.org/1999/xlink'
FB2_NSMAP = {
    'fb': FB2_NS,
    'l': XLINK_NS,
}

# Пространства имён EPUB
EPUB_CONTAINER_NS = 'urn:oasis:names:tc:opendocument:xmlns:container'
OPF_NS = 'http://www.idpf.org/2007/opf'
DC_NS = 'http://purl.org/dc/elements/1.1/'
XHTML_NS = 'http://www.w3.org/1999/xhtml'
EPUB_NS = 'http://www.idpf.org/2007/ops'

def _image_dimensions(data):
    """Размеры изображения (width, height) по бинарным данным.

    Сначала пробует Pillow (если установлен), иначе парсит заголовки
    вручную. Возвращает (None, None) при неизвестном формате.
    """
    if not data:
        return (None, None)
    try:
        from PIL import Image
        with Image.open(BytesIO(data)) as im:
            return im.size
    except Exception:
        pass
    return _sniff_image_size(data)

def _image_quality(data):
    """Оценка качества картинки: число пикселей или длина данных.

    Используется для выбора лучшей копии, если в файле есть несколько
    бинарников с одинаковым id.
    """
    w, h = _image_dimensions(data)
    if w and h:
        return w * h
    return len(data) if data else 0

def _sniff_image_size(data):
    """Резервный парсер размеров без Pillow: PNG, GIF, JPEG, WebP, BMP."""
    try:
        if data[:8] == b'\x89PNG\r\n\x1a\n' and len(data) >= 24:
            return struct.unpack('>II', data[16:24])

        if data[:6] in (b'GIF87a', b'GIF89a') and len(data) >= 10:
            return struct.unpack('<HH', data[6:10])

        if data[:2] == b'\xff\xd8':
            return _jpg_size(data)

        if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            return _webp_size(data)

        if data[:2] == b'BM' and len(data) >= 26:
            w = struct.unpack('<I', data[18:22])[0]
            h = abs(struct.unpack('<i', data[22:26])[0])
            return (w, h)
    except Exception:
        pass
    return (None, None)

def _jpg_size(data):
    i = 2
    n = len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        if data[i + 1] == 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker == 0xDA:  # SOS — дальше закодированные данные
            break
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height = struct.unpack('>H', data[i + 5:i + 7])[0]
            width = struct.unpack('>H', data[i + 7:i + 9])[0]
            return (width, height)
        seg_len = struct.unpack('>H', data[i + 2:i + 4])[0]
        i += 2 + seg_len
    return (None, None)

def _webp_size(data):
    if data[12:16] == b'VP8 ' and len(data) >= 30:
        w = struct.unpack('<H', data[26:28])[0] & 0x3FFF
        h = struct.unpack('<H', data[28:30])[0] & 0x3FFF
        return (w, h)
    if data[12:16] == b'VP8L' and len(data) >= 26 and data[21] == 0x2F:
        bits = struct.unpack('<I', data[22:26])[0]
        return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
    if data[12:16] == b'VP8X' and len(data) >= 30:
        w = struct.unpack('<I', data[24:27] + b'\x00')[0] + 1
        h = struct.unpack('<I', data[27:30] + b'\x00')[0] + 1
        return (w, h)
    return (None, None)

def _read_fb2_root(filepath):
    """Читает FB2 (или .zip с FB2 внутри) и возвращает корень XML."""
    filepath = str(filepath)
    if filepath.lower().endswith('.zip'):
        with zipfile.ZipFile(filepath, 'r') as z:
            for name in z.namelist():
                if name.lower().endswith('.fb2'):
                    data = z.read(name)
                    break
            else:
                data = z.read(z.namelist()[0])
        return ET.fromstring(data)
    return ET.parse(filepath).getroot()

def fb2_find(element, path):
    """Поиск элемента с учётом пространства имён FB2."""
    parts = path.split('/')
    ns_path = '/'.join(f'{{{FB2_NS}}}{p}' if not p.startswith('{') else p for p in parts)
    return element.find(ns_path)

def fb2_findall(element, path):
    """Поиск всех элементов с учётом пространства имён FB2."""
    parts = path.split('/')
    ns_path = '/'.join(f'{{{FB2_NS}}}{p}' if not p.startswith('{') else p for p in parts)
    return element.findall(ns_path)

def fb2_findtext(element, path, default=''):
    """Получение текста элемента с учётом пространства имён FB2."""
    el = fb2_find(element, path)
    if el is not None:
        return (el.text or '').strip()
    return default

def get_text_content(element):
    """Рекурсивно извлекает весь текст из элемента."""
    texts = []
    if element.text:
        texts.append(element.text)
    for child in element:
        texts.append(get_text_content(child))
        if child.tail:
            texts.append(child.tail)
    return ''.join(texts)

class FB2Book:
    """Парсер FB2-файла."""
    def __init__(self):
        self.title = ''
        self.authors = []
        self.lang = 'ru'
        self.book_id = ''
        self.genres = []
        self.annotation = None
        self.date = ''
        self.publisher = ''
        self.year = ''
        self.isbn = ''
        self.series_name = ''
        self.series_number = ''
        self.coverpage_image_id = ''
        self.sections = []
        self.binaries = {}  # id -> (content_type, data_bytes)
        self.epigraphs = []
        self.body_element = None
        self.extra_bodies = []  # notes и т.д.

    def parse(self, filepath):
        """Парсинг FB2-файла."""
        root = _read_fb2_root(filepath)
        self._parse_description(root)
        self._parse_bodies(root)
        self._parse_binaries(root)

    def _parse_description(self, root):
        """Парсинг метаданных книги."""
        desc = fb2_find(root, 'description')
        if desc is None:
            return

        # title-info
        title_info = fb2_find(desc, 'title-info')
        if title_info is not None:
            self.title = fb2_findtext(title_info, 'book-title') or 'Untitled'
            
            # Авторы
            for author_el in fb2_findall(title_info, 'author'):
                first = fb2_findtext(author_el, 'first-name')
                middle = fb2_findtext(author_el, 'middle-name')
                last = fb2_findtext(author_el, 'last-name')
                nickname = fb2_findtext(author_el, 'nickname')
                parts = [p for p in [first, middle, last] if p]
                name = ' '.join(parts) if parts else nickname or 'Unknown'
                self.authors.append(name)
            
            if not self.authors:
                self.authors = ['Unknown']
            self.lang = fb2_findtext(title_info, 'lang') or 'ru'

            # Жанры
            for genre_el in fb2_findall(title_info, 'genre'):
                if genre_el.text:
                    self.genres.append(genre_el.text.strip())

            # Аннотация
            self.annotation = fb2_find(title_info, 'annotation')

            # Дата
            date_el = fb2_find(title_info, 'date')
            if date_el is not None:
                self.date = date_el.get('value', '') or (date_el.text or '').strip()

            # Обложка
            coverpage = fb2_find(title_info, 'coverpage')
            if coverpage is not None:
                image = fb2_find(coverpage, 'image')
                if image is not None:
                    href = image.get(f'{{{XLINK_NS}}}href', '')
                    if href.startswith('#'):
                        href = href[1:]
                    self.coverpage_image_id = href

            # Серия
            sequence = fb2_find(title_info, 'sequence')
            if sequence is not None:
                self.series_name = sequence.get('name', '')
                self.series_number = sequence.get('number', '')

        # publish-info
        publish_info = fb2_find(desc, 'publish-info')
        if publish_info is not None:
            self.publisher = fb2_findtext(publish_info, 'publisher')
            self.year = fb2_findtext(publish_info, 'year')
            self.isbn = fb2_findtext(publish_info, 'isbn')

        # document-info — id
        doc_info = fb2_find(desc, 'document-info')
        if doc_info is not None:
            self.book_id = fb2_findtext(doc_info, 'id')
        if not self.book_id:
            self.book_id = str(uuid.uuid4())

    def _parse_bodies(self, root):
        """Парсинг тел книги."""
        bodies = fb2_findall(root, 'body')
        for i, body in enumerate(bodies):
            body_name = body.get('name', '')
            if i == 0 and not body_name:
                self.body_element = body
                # Эпиграфы на уровне body
                for epigraph in fb2_findall(body, 'epigraph'):
                    self.epigraphs.append(epigraph)
                # Секции
                for section in fb2_findall(body, 'section'):
                    self.sections.append(section)
            else:
                self.extra_bodies.append(body)

    def _parse_binaries(self, root):
        """Парсинг бинарных данных (изображения).

        При дублирующемся id оставляем лучшую по качеству картинку,
        чтобы плохая копия не перетирала хорошую.
        """
        for binary in fb2_findall(root, 'binary'):
            binary_id = binary.get('id', '')
            content_type = binary.get('content-type', 'application/octet-stream')
            if not binary.text:
                continue
            data = base64.b64decode(binary.text.strip())
            old = self.binaries.get(binary_id)
            if old is not None and _image_quality(data) < _image_quality(old[1]):
                continue
            self.binaries[binary_id] = (content_type, data)

class FB2ToXHTMLConverter:
    """Конвертер элементов FB2 в XHTML."""
    def __init__(self, book: FB2Book):
        self.book = book
        self.footnotes = {}  # id -> xhtml content
        self.image_files = {}  # id -> filename
        self.current_note_id = None
        self._prepare_images()
        self._parse_notes()

    def _prepare_images(self):
        """Подготовка имён файлов изображений."""
        for binary_id, (content_type, data) in self.book.binaries.items():
            ext = mimetypes.guess_extension(content_type) or '.bin'
            if ext == '.jpe':
                ext = '.jpg'
            safe_name = re.sub(r'[^\w\-.]', '_', binary_id)
            if not safe_name.lower().endswith(ext):
                safe_name += ext
            self.image_files[binary_id] = f'images/{safe_name}'

    def _parse_notes(self):
        """Парсинг примечаний из дополнительных body."""
        for body in self.book.extra_bodies:
            body_name = body.get('name', '')
            for section in fb2_findall(body, 'section'):
                section_id = section.get('id', '')
                if section_id:
                    self.footnotes[section_id] = section

    def _get_image_filename(self, href):
        """Получение имени файла изображения по ссылке."""
        if href.startswith('#'):
            href = href[1:]
        return self.image_files.get(href, '')

    def convert_section(self, section, level=1, split=None):
        """Конвертация секции FB2 в XHTML-строку.

        split — необязательный колбэк (el, level) -> bool. Если он возвращает
        True для вложенной секции, она не попадает в этот файл: вызывающий
        код берёт её на себя (отдельный файл главы).
        """
        lines = []
        title_text = ''

        # Обработка заголовка секции
        title_el = fb2_find(section, 'title')
        if title_el is not None:
            title_text = self._convert_title(title_el, level)
            lines.append(title_text)

        # Эпиграф секции
        for epigraph in fb2_findall(section, 'epigraph'):
            lines.append(self._convert_epigraph(epigraph))

        # Изображение секции
        for image in fb2_findall(section, 'image'):
            lines.append(self._convert_image(image))

        # Аннотация секции
        annotation = fb2_find(section, 'annotation')
        if annotation is not None:
            lines.append(self._convert_annotation(annotation))

        # Содержимое секции
        for child in section:
            tag = self._local_tag(child)
            if tag in ('title', 'epigraph', 'image', 'annotation'):
                continue
            elif tag == 'section':
                if split is not None and split(child, level + 1):
                    continue
                lines.append(self.convert_section(child, level + 1))
            elif tag == 'p':
                lines.append(self._convert_p(child))
            elif tag == 'poem':
                lines.append(self._convert_poem(child))
            elif tag == 'cite':
                lines.append(self._convert_cite(child))
            elif tag == 'subtitle':
                lines.append(self._convert_subtitle(child))
            elif tag == 'empty-line':
                lines.append('<p class="empty-line">&#160;</p>')
            elif tag == 'table':
                lines.append(self._convert_table(child))
            elif tag == 'code':
                lines.append(f'<pre><code>{self._escape(get_text_content(child))}</code></pre>')
            else:
                # Попытка обработать как параграф
                text = get_text_content(child)
                if text.strip():
                    lines.append(f'<p>{self._escape(text)}</p>')

        return '\n'.join(lines)

    def _convert_title(self, title_el, level=1, anchor=''):
        """Конвертация заголовка."""
        h_level = min(level, 6)
        parts = []
        for child in title_el:
            tag = self._local_tag(child)
            if tag == 'p':
                parts.append(self._inline_content(child))
            elif tag == 'empty-line':
                parts.append('')
        text = '<br/>'.join(parts) if parts else get_text_content(title_el).strip()
        id_attr = f' id="{anchor}"' if anchor else ''
        return f'<h{h_level}{id_attr}>{text}</h{h_level}>'

    def _convert_subtitle(self, el):
        """Конвертация подзаголовка."""
        return f'<h4 class="subtitle">{self._inline_content(el)}</h4>'

    def _convert_epigraph(self, epigraph):
        """Конвертация эпиграфа."""
        lines = ['<div class="epigraph">']
        for child in epigraph:
            tag = self._local_tag(child)
            if tag == 'p':
                lines.append(f'<p>{self._inline_content(child)}</p>')
            elif tag == 'poem':
                lines.append(self._convert_poem(child))
            elif tag == 'cite':
                lines.append(self._convert_cite(child))
            elif tag == 'text-author':
                lines.append(f'<p class="text-author">— {self._inline_content(child)}</p>')
            elif tag == 'empty-line':
                lines.append('<p class="empty-line">&#160;</p>')
        lines.append('</div>')
        return '\n'.join(lines)

    def _convert_annotation(self, annotation):
        """Конвертация аннотации."""
        lines = ['<div class="annotation">']
        for child in annotation:
            tag = self._local_tag(child)
            if tag == 'p':
                lines.append(f'<p>{self._inline_content(child)}</p>')
            elif tag == 'poem':
                lines.append(self._convert_poem(child))
            elif tag == 'cite':
                lines.append(self._convert_cite(child))
            elif tag == 'subtitle':
                lines.append(self._convert_subtitle(child))
            elif tag == 'empty-line':
                lines.append('<p class="empty-line">&#160;</p>')
        lines.append('</div>')
        return '\n'.join(lines)

    def _convert_p(self, p_el):
        """Конвертация параграфа."""
        p_id = p_el.get('id', '')
        id_attr = f' id="{p_id}"' if p_id else ''
        return f'<p{id_attr}>{self._inline_content(p_el)}</p>'

    def _convert_poem(self, poem):
        """Конвертация стихотворения."""
        lines = ['<div class="poem">']
        for child in poem:
            tag = self._local_tag(child)
            if tag == 'title':
                lines.append(self._convert_title(child, 4))
            elif tag == 'epigraph':
                lines.append(self._convert_epigraph(child))
            elif tag == 'stanza':
                lines.append('<div class="stanza">')
                for v in fb2_findall(child, 'v'):
                    lines.append(f'<p class="verse">{self._inline_content(v)}</p>')
                lines.append('</div>')
            elif tag == 'text-author':
                lines.append(f'<p class="text-author">— {self._inline_content(child)}</p>')
            elif tag == 'date':
                lines.append(f'<p class="date">{self._inline_content(child)}</p>')
        lines.append('</div>')
        return '\n'.join(lines)

    def _convert_cite(self, cite):
        """Конвертация цитаты."""
        lines = ['<blockquote class="cite">']
        for child in cite:
            tag = self._local_tag(child)
            if tag == 'p':
                lines.append(f'<p>{self._inline_content(child)}</p>')
            elif tag == 'poem':
                lines.append(self._convert_poem(child))
            elif tag == 'subtitle':
                lines.append(self._convert_subtitle(child))
            elif tag == 'text-author':
                lines.append(f'<p class="text-author">— {self._inline_content(child)}</p>')
            elif tag == 'empty-line':
                lines.append('<p class="empty-line">&#160;</p>')
        lines.append('</blockquote>')
        return '\n'.join(lines)

    def _convert_image(self, image):
        """Конвертация изображения."""
        href = image.get(f'{{{XLINK_NS}}}href', '')
        img_file = self._get_image_filename(href)
        if img_file:
            alt = image.get('alt', '')
            title = image.get('title', '')
            title_attr = f' title="{self._escape(title)}"' if title else ''
            return f'<div class="image"><img src="{img_file}" alt="{self._escape(alt)}"{title_attr}/></div>'
        return ''

    def _convert_table(self, table):
        """Конвертация таблицы."""
        lines = ['<table>']
        for tr in fb2_findall(table, 'tr'):
            lines.append('<tr>')
            for child in tr:
                tag = self._local_tag(child)
                if tag == 'th':
                    colspan = child.get('colspan', '')
                    rowspan = child.get('rowspan', '')
                    attrs = ''
                    if colspan: attrs += f' colspan="{colspan}"'
                    if rowspan: attrs += f' rowspan="{rowspan}"'
                    lines.append(f'<th{attrs}>{self._inline_content(child)}</th>')
                elif tag == 'td':
                    colspan = child.get('colspan', '')
                    rowspan = child.get('rowspan', '')
                    attrs = ''
                    if colspan: attrs += f' colspan="{colspan}"'
                    if rowspan: attrs += f' rowspan="{rowspan}"'
                    lines.append(f'<td{attrs}>{self._inline_content(child)}</td>')
            lines.append('</tr>')
        lines.append('</table>')
        return '\n'.join(lines)

    def _inline_content(self, element):
        """Конвертация инлайн-содержимого элемента."""
        result = []
        if element.text:
            result.append(self._escape(element.text))
        for child in element:
            tag = self._local_tag(child)
            if tag == 'strong':
                result.append(f'<strong>{self._inline_content(child)}</strong>')
            elif tag == 'emphasis':
                result.append(f'<em>{self._inline_content(child)}</em>')
            elif tag == 'strikethrough':
                result.append(f'<del>{self._inline_content(child)}</del>')
            elif tag == 'sub':
                result.append(f'<sub>{self._inline_content(child)}</sub>')
            elif tag == 'sup':
                result.append(f'<sup>{self._inline_content(child)}</sup>')
            elif tag == 'code':
                result.append(f'<code>{self._inline_content(child)}</code>')
            elif tag == 'style':
                result.append(f'<span>{self._inline_content(child)}</span>')
            elif tag == 'a':
                href = child.get(f'{{{XLINK_NS}}}href', '')
                text = self._inline_content(child)
                if href.startswith('#'):
                    note_id = href[1:]
                    if note_id in self.footnotes:
                        result.append(
                            f'<a epub:type="noteref" href="notes.xhtml#{note_id}"'
                            f' class="note-ref">{text}</a>'
                        )
                    else:
                        result.append(f'<a href="{href}">{text}</a>')
                else:
                    result.append(f'<a href="{href}">{text}</a>')
            elif tag == 'image':
                img_href = child.get(f'{{{XLINK_NS}}}href', '')
                img_file = self._get_image_filename(img_href)
                if img_file:
                    result.append(f'<img src="{img_file}" alt="" class="inline-image"/>')
                else:
                    result.append(self._inline_content(child))
            if child.tail:
                result.append(self._escape(child.tail))
        return ''.join(result)

    def _local_tag(self, element):
        """Получение локального имени тега без namespace."""
        tag = element.tag
        if '}' in tag:
            return tag.split('}', 1)[1]
        return tag

    def _escape(self, text):
        """HTML-экранирование текста."""
        if not text:
            return ''
        text = text.replace('&', '&amp;')
        text = text.replace('<', '&lt;')
        text = text.replace('>', '&gt;')
        text = text.replace('"', '&quot;')
        return text

class EPUBBuilder:
    """Построитель EPUB 3 файла."""
    STYLESHEET = """
body {
    font-family: serif;
    margin: 1em;
    line-height: 1.6;
}
h1, h2, h3, h4, h5, h6 {
    text-align: center;
    margin: 1.5em 0 0.5em 0;
    font-weight: bold;
}
h1 { font-size: 1.8em; }
h2 { font-size: 1.5em; }
h3 { font-size: 1.3em; }
h4 { font-size: 1.1em; }
p {
    text-indent: 1.5em;
    margin: 0.2em 0;
    text-align: justify;
}
p.empty-line {
    text-indent: 0;
    margin: 0.5em 0;
}
.subtitle {
    text-align: center;
    font-style: italic;
}
.epigraph {
    margin: 1em 0 1em 30%;
    font-style: italic;
    font-size: 0.9em;
}
.epigraph p { text-indent: 0; }
.annotation {
    margin: 1em 2em;
    font-style: italic;
    border-left: 3px solid #ccc;
    padding-left: 1em;
}
.annotation p { text-indent: 0; }
.poem { margin: 1em 2em; }
.stanza { margin: 0.5em 0; }
.verse { text-indent: 0; text-align: left; }
blockquote.cite {
    margin: 1em 2em;
    border-left: 3px solid #999;
    padding-left: 1em;
}
blockquote.cite p { text-indent: 0; }
.text-author {
    text-indent: 0;
    text-align: right;
    font-style: italic;
    margin-top: 0.5em;
}
.image {
    text-align: center;
    margin: 1em 0;
}
.image img {
    max-width: 100%;
    max-height: 90vh;
}
.inline-image {
    vertical-align: middle;
    max-height: 1.5em;
}
.title-page {
    text-align: center;
    margin-top: 20%;
}
.title-page h1 {
    font-size: 2em;
    margin-bottom: 0.5em;
}
.title-page .author {
    font-size: 1.3em;
    margin-bottom: 1em;
}
.title-page .series {
    font-style: italic;
    margin-top: 1em;
}
a.note-ref {
    font-size: 0.8em;
    vertical-align: super;
    text-decoration: none;
    color: #0066cc;
}
.footnote {
    margin: 1em 0;
    padding: 0.5em 0;
    border-top: 1px solid #eee;
    font-size: 0.9em;
}
.footnote-title {
    font-weight: bold;
    margin-bottom: 0.3em;
}
table {
    border-collapse: collapse;
    margin: 1em auto;
}
td, th {
    border: 1px solid #999;
    padding: 0.3em 0.5em;
}
th {
    background-color: #f0f0f0;
    font-weight: bold;
}
.date {
    text-indent: 0;
    text-align: right;
    font-style: italic;
}
"""

    MAX_SPLIT_LEVEL = 2  # до какого уровня вложенности секция получает свой файл

    def __init__(self, book: FB2Book):
        self.book = book
        self.converter = FB2ToXHTMLConverter(book)
        # Словари: file, title, content, toc [(label, href), ...]
        self.chapters = []
        self.spine_items = []  # (id, filename)
        self.manifest_items = []  # (id, filename, media_type, properties)
        self.frontmatter_content = ""
        self.chapter_idx = 1
        self.part_idx = 1

    def build(self, output_path):
        """Построение EPUB-файла."""
        self._prepare_chapters()
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as epub:
            # mimetype (без сжатия, первый файл!)
            epub.writestr('mimetype', 'application/epub+zip', compress_type=zipfile.ZIP_STORED)
            # META-INF/container.xml
            epub.writestr('META-INF/container.xml', self._build_container())
            # Стили
            epub.writestr('OEBPS/style.css', self.STYLESHEET)
            self.manifest_items.append(('style', 'style.css', 'text/css', ''))
            # Изображения
            self._write_images(epub)
            # Титульная страница
            self._build_title_page(epub)
            # Обложка (если есть)
            self._build_cover_page(epub)
            
            # Frontmatter (вступительные части без заголовков)
            if getattr(self, 'frontmatter_content', ''):
                xhtml = self._wrap_xhtml('', self.frontmatter_content, body_style="margin: 1em;")
                epub.writestr('OEBPS/frontmatter.xhtml', xhtml)

            # Главы
            for chapter in self.chapters:
                xhtml = self._wrap_xhtml(chapter['title'], chapter['content'])
                epub.writestr(f'OEBPS/{chapter["file"]}', xhtml)
                
            # Примечания
            if self.converter.footnotes:
                self._build_notes_page(epub)
                
            # Оглавление (nav)
            nav_content = self._build_nav()
            epub.writestr('OEBPS/nav.xhtml', nav_content)
            self.manifest_items.append(('nav', 'nav.xhtml', 'application/xhtml+xml', 'nav'))
            self.spine_items.append(('nav', 'nav.xhtml'))
            
            # OPF
            epub.writestr('OEBPS/content.opf', self._build_opf())
        toc_items = sum(len(c['toc']) for c in self.chapters)
        print(f'EPUB создан: {output_path} '
              f'(файлов глав: {len(self.chapters)}, пунктов оглавления: {toc_items})')

    def _smart_trim_inferred_title(self, s, max_chars=60, max_words=12):
        """Красиво обрезать предполагаемый заголовок."""
        if not s:
            return ''
        # Нормализуем пробелы
        s = re.sub(r'[\r\n\t]+', ' ', s)
        s = re.sub(r'\s+', ' ', s).strip()
        if not s:
            return ''
        # Пытаемся взять первое предложение по . ! ?
        m = re.match(r'(.+?[.!?])(?:\s|$)', s)
        cand = m.group(1).strip() if m else s
        # Если первое предложение слишком короткое (< 10 символов) или
        # не заканчивается знаком — можно взять чуть больше, но не навязчиво
        # Обрезаем по символам, не рвём слова
        if len(cand) > max_chars:
            # режем по словам
            words = cand.split()
            res = []
            total = 0
            for w in words:
                if total + len(w) + (1 if res else 0) > max_chars:
                    break
                res.append(w)
                total += len(w) + 1
            cand2 = ' '.join(res).rstrip('.,:;!?')
            cand = cand2 if cand2 else cand[:max_chars].rstrip()
        # Если после всех манипуляций пусто — возвращаем обрезанный по словам оригинал
        if not cand:
            words = s.split()
            res = []
            total = 0
            for w in words:
                if total + len(w) + 1 > max_chars and res:
                    break
                res.append(w)
                total += len(w) + 1
            cand = ' '.join(res)
        return cand.strip()

    def _infer_section_title(self, section):
        """Инферировать заголовок из первого отображаемого текста секции."""
        # Ищем первый отображаемый текстовый элемент в документном порядке
        for child in section:
            tag = self.converter._local_tag(child)
            if tag in ('title', 'section'):
                continue
            if tag in ('empty-line',):
                continue
            if tag == 'image':
                # Изображение не даёт текстового заголовка
                continue
            # Подходящие текстовые блоки
            if tag in ('epigraph', 'p', 'subtitle', 'cite', 'annotation', 'text-author'):
                text = get_text_content(child)
                text = text.strip()
                if text:
                    return self._smart_trim_inferred_title(text)
            # poem — берём первую строку/первый абзац
            if tag == 'poem':
                # poem может содержать stanza/v или p
                text = get_text_content(child)
                text = text.strip()
                if text:
                    return self._smart_trim_inferred_title(text)
            # table, code — пропускаем как не заголовочные
            if tag in ('table', 'code'):
                continue
            # Прочие элементы — пробуем получить текст
            text = get_text_content(child)
            text = text.strip()
            if text:
                return self._smart_trim_inferred_title(text)
        return ''

    def _title_text(self, section):
        """Текст title-элемента секции ('' если собственного заголовка нет)."""
        title_el = fb2_find(section, 'title')
        if title_el is None:
            return ''
        return ' '.join(get_text_content(title_el).split())

    def _section_title(self, section):
        """Нормализованный текст заголовка секции ('' если заголовка нет)."""
        t = self._title_text(section)
        if t:
            return t
        t = self._infer_section_title(section)
        if not t:
            return '***'
        return t

    def _section_has_own_content(self, section):
        """Есть ли у секции собственный текст (помимо заголовка и вложенных секций)."""
        for child in section:
            tag = self.converter._local_tag(child)
            if tag in ('section', 'title', 'empty-line'):
                continue
            if tag == 'image' or get_text_content(child).strip():
                return True
        return False

    def _can_split(self, section, level):
        """Можно ли вынести секцию в отдельный файл главы."""
        if level > self.MAX_SPLIT_LEVEL or level < 2:
            return False
        title = self._section_title(section)
        if not title:
            return False
        # Заголовки вида «1», «2» (письма, тома) — не оглавление, а шум
        if re.fullmatch(r'[\W\d_]+', title):
            return False
        return self._section_has_own_content(section)

    def _is_transparent_part(self, section, level):
        """Является ли секция «частью» без собственного текста (том, книга).

        Такая секция — только заголовок и вложенные секции, при этом все
        вложенные секции уходят в отдельные файлы. Своего файла часть не
        получает (см. _fold_part_files), и уровень вложенности для её глав
        не увеличивается: главы части считаются главами родительской секции.
        Иначе книги вида «роман -> часть -> глава» целиком сливались бы
        в один файл, не проходя по MAX_SPLIT_LEVEL.
        """
        if level + 1 > self.MAX_SPLIT_LEVEL:
            return False
        title = self._title_text(section)
        if not title or re.fullmatch(r'[\W\d_]+', title):
            return False
        if self._section_has_own_content(section):
            return False
        kids = [c for c in section if self.converter._local_tag(c) == 'section']
        if not kids:
            return False
        for kid in kids:
            if not (self._can_split(kid, level + 1)
                    or self._is_transparent_part(kid, level)):
                return False
        return True

    def _fold_part_files(self, section, level):
        """Файлы для «части» без своего файла.

        Заголовок части печатается в начале первой созданной главы и
        связывается из оглавления якорем. Вложенные прозрачные части
        сворачиваются рекурсивно на том же уровне.
        """
        first_idx = len(self.chapters)
        for child in section:
            if self.converter._local_tag(child) != 'section':
                continue
            if self._can_split(child, level + 1):
                self._add_section_files(child, level + 1)
            elif self._is_transparent_part(child, level):
                self._fold_part_files(child, level)
        if len(self.chapters) == first_idx:
            # Страховка: ничего не вынеслось — выводим секцию целиком главой.
            title = self._section_title(section)
            self._add_chapter(title,
                              self.converter.convert_section(section, level),
                              [(title, None)])
            return
        title = self._title_text(section)
        if not title:
            return
        anchor = f'part-{self.part_idx}'
        self.part_idx += 1
        first = self.chapters[first_idx]
        heading = self.converter._convert_title(fb2_find(section, 'title'),
                                                level, anchor)
        first['content'] = heading + '\n' + first['content']
        first['toc'].insert(0, (title, f"{first['file']}#{anchor}"))

    def _add_chapter(self, title, content, toc):
        """Регистрация файла главы в chapters/manifest/spine."""
        stem = f'chapter_{self.chapter_idx:03d}'
        self.chapter_idx += 1
        self.chapters.append({
            'file': f'{stem}.xhtml',
            'title': title,
            'content': content,
            'toc': toc,
        })
        self.manifest_items.append((stem, f'{stem}.xhtml', 'application/xhtml+xml', ''))
        self.spine_items.append((stem, f'{stem}.xhtml'))

    def _add_section_files(self, section, level):
        """Файлы для секции и всех вложенных секций, которые уходят в отдельные файлы."""
        kids = [c for c in section if self.converter._local_tag(c) == 'section']
        splittable = [c for c in kids if self._can_split(c, level + 1)]
        parts = [c for c in kids if c not in splittable
                 and self._is_transparent_part(c, level)]
        title = self._section_title(section)

        # «Часть» без своего текста (только заголовок + главы) не заслуживает
        # отдельного файла: её заголовок печатается в начале первой главы.
        if (splittable or parts) and len(splittable) + len(parts) == len(kids) \
                and not self._section_has_own_content(section):
            self._fold_part_files(section, level)
            return

        pending = []

        def split(el, _level):
            if self._can_split(el, _level):
                pending.append((el, False))
                return True
            if self._is_transparent_part(el, level):
                pending.append((el, True))
                return True
            return False

        content = self.converter.convert_section(section, level, split)
        if not title:
            title = '***'
        self._add_chapter(title, content, [(title, None)])
        for kid, is_part in pending:
            if is_part:
                self._fold_part_files(kid, level)
            else:
                self._add_section_files(kid, level + 1)

    def _prepare_chapters(self):
        """Подготовка глав из секций FB2."""
        self.frontmatter_content = ""
        if not self.book.sections:
            if self.book.body_element is not None:
                content = self.converter.convert_section(self.book.body_element, 1)
                self._add_chapter(self.book.title, content,
                                  [(self.book.title, None)])
            return

        frontmatter_parts = []
        found_first_title = False

        for section in self.book.sections:
            if fb2_find(section, 'title') is None and not found_first_title:
                # Секция без заголовка в самом начале книги (титул, копирайт, аннотация)
                frontmatter_parts.append(self.converter.convert_section(section, 1))
            else:
                found_first_title = True
                self._add_section_files(section, 1)

        if not self.chapters and frontmatter_parts:
            # Если вообще нет заголовков, делаем всё одной главой
            self._add_chapter(self.book.title, '\n'.join(frontmatter_parts),
                              [(self.book.title, None)])
        elif frontmatter_parts:
            self.frontmatter_content = '\n'.join(frontmatter_parts)
            self.manifest_items.insert(0, ('frontmatter', 'frontmatter.xhtml', 'application/xhtml+xml', ''))
            self.spine_items.insert(0, ('frontmatter', 'frontmatter.xhtml'))

    def _write_images(self, epub):
        """Запись изображений в EPUB."""
        for binary_id, (content_type, data) in self.book.binaries.items():
            filename = self.converter.image_files.get(binary_id, '')
            if filename:
                epub.writestr(f'OEBPS/{filename}', data)
                item_id = re.sub(r'[^\w]', '_', binary_id)
                properties = ''
                if binary_id == self.book.coverpage_image_id:
                    properties = 'cover-image'
                self.manifest_items.append(
                    (f'img_{item_id}', filename, content_type, properties)
                )

    def _build_cover_page(self, epub):
        """Построение страницы с обложкой."""
        if not self.book.coverpage_image_id:
            return
        img_file = self.converter.image_files.get(self.book.coverpage_image_id, '')
        if not img_file:
            return

        # Размеры берём из бинарника, чтобы SVG сохранил пропорции картинки.
        binary = self.book.binaries.get(self.book.coverpage_image_id)
        width, height = _image_dimensions(binary[1]) if binary else (None, None)
        if not width or not height:
            width, height = (600, 900)  # резервная книжная пропорция

        # Обложка вписывается в страницу целиком без искажения через SVG.
        # SVG знает собственные пропорции (viewBox), поэтому ридер никогда
        # не растянет картинку по горизонтали при малой высоте.
        content = (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'xmlns:xlink="http://www.w3.org/1999/xlink" version="1.1" '
            f'width="100%" height="100%" viewBox="0 0 {width} {height}" '
            f'preserveAspectRatio="xMidYMid meet">'
            f'<image width="{width}" height="{height}" xlink:href="{img_file}"/>'
            f'</svg>'
        )

        xhtml = self._wrap_xhtml('Cover', content, body_style="margin: 0; padding: 0;")
        epub.writestr('OEBPS/cover.xhtml', xhtml)
        self.manifest_items.insert(0, ('cover', 'cover.xhtml', 'application/xhtml+xml', ''))
        self.spine_items.insert(0, ('cover', 'cover.xhtml'))

    def _build_title_page(self, epub):
        """Построение титульной страницы."""
        lines = ['<div class="title-page">']
        for author in self.book.authors:
            lines.append(f'<p class="author">{self.converter._escape(author)}</p>')
        lines.append(f'<h1>{self.converter._escape(self.book.title)}</h1>')
        if self.book.series_name:
            series_text = self.book.series_name
            if self.book.series_number:
                series_text += f' #{self.book.series_number}'
            lines.append(f'<p class="series">{self.converter._escape(series_text)}</p>')
        if self.book.annotation is not None:
            lines.append('<div class="annotation">')
            for child in self.book.annotation:
                tag = self.converter._local_tag(child)
                if tag == 'p':
                    lines.append(f'<p>{self.converter._inline_content(child)}</p>')
                elif tag == 'empty-line':
                    lines.append('<p class="empty-line">&#160;</p>')
            lines.append('</div>')
        lines.append('</div>')
        content = '\n'.join(lines)
        xhtml = self._wrap_xhtml('Title', content)
        epub.writestr('OEBPS/title.xhtml', xhtml)
        self.manifest_items.insert(0, ('title_page', 'title.xhtml', 'application/xhtml+xml', ''))
        self.spine_items.insert(0, ('title_page', 'title.xhtml'))

    def _build_notes_page(self, epub):
        """Построение страницы примечаний."""
        lines = ['<section epub:type="endnotes">', '<h1>Примечания</h1>']
        for note_id, section in self.converter.footnotes.items():
            lines.append(f'<aside epub:type="footnote" id="{note_id}" class="footnote">')
            for child in section:
                tag = self.converter._local_tag(child)
                if tag == 'title':
                    title_text = get_text_content(child).strip()
                    lines.append(f'<p class="footnote-title">{self.converter._escape(title_text)}</p>')
                elif tag == 'p':
                    lines.append(f'<p>{self.converter._inline_content(child)}</p>')
                elif tag == 'empty-line':
                    lines.append('<p class="empty-line">&#160;</p>')
            lines.append('</aside>')
        lines.append('</section>')
        content = '\n'.join(lines)
        xhtml = self._wrap_xhtml('Примечания', content)
        epub.writestr('OEBPS/notes.xhtml', xhtml)
        self.manifest_items.append(('notes', 'notes.xhtml', 'application/xhtml+xml', ''))
        self.spine_items.append(('notes', 'notes.xhtml'))

    def _build_container(self):
        """Построение container.xml."""
        return '''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles>
<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
</rootfiles>
</container>'''

    def _build_opf(self):
        """Построение content.opf."""
        # Исправлено: используем timezone-aware datetime
        now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="BookId">',
            '',
            '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">',
            f'    <dc:identifier id="BookId">urn:uuid:{self.book.book_id}</dc:identifier>',
            f'    <dc:title>{self._escape_xml(self.book.title)}</dc:title>',
            f'    <dc:language>{self.book.lang}</dc:language>',
        ]
        for author in self.book.authors:
            lines.append(f'    <dc:creator>{self._escape_xml(author)}</dc:creator>')
        if self.book.date:
            lines.append(f'    <dc:date>{self._escape_xml(self.book.date)}</dc:date>')
        if self.book.publisher:
            lines.append(f'    <dc:publisher>{self._escape_xml(self.book.publisher)}</dc:publisher>')
        if self.book.isbn:
            lines.append(f'    <dc:identifier>isbn:{self._escape_xml(self.book.isbn)}</dc:identifier>')
        for genre in self.book.genres:
            lines.append(f'    <dc:subject>{self._escape_xml(genre)}</dc:subject>')
        lines.append(f'    <meta property="dcterms:modified">{now}</meta>')
        if self.book.series_name:
            lines.append(f'    <meta property="belongs-to-collection">{self._escape_xml(self.book.series_name)}</meta>')
            lines.append(f'    <meta property="collection-type">series</meta>')
        if self.book.series_number:
            lines.append(f'    <meta property="group-position">{self.book.series_number}</meta>')
        lines.append('  </metadata>')
        lines.append('')
        
        # Manifest
        lines.append('  <manifest>')
        for item_id, filename, media_type, properties in self.manifest_items:
            props_attr = f' properties="{properties}"' if properties else ''
            lines.append(f'    <item id="{item_id}" href="{filename}" media-type="{media_type}"{props_attr}/>')
        lines.append('  </manifest>')
        lines.append('')
        
        # Spine
        lines.append('  <spine>')
        for item_id, filename in self.spine_items:
            lines.append(f'    <itemref idref="{item_id}"/>')
        lines.append('  </spine>')
        lines.append('')
        lines.append('</package>')
        return '\n'.join(lines)

    def _build_nav(self):
        """Построение навигационного документа (nav.xhtml)."""
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<!DOCTYPE html>',
            '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">',
            '<head>',
            '  <meta charset="UTF-8"/>',
            '  <title>Содержание</title>',
            '  <link rel="stylesheet" type="text/css" href="style.css"/>',
            '</head>',
            '<body>',
            '  <nav epub:type="toc" id="toc">',
            '    <h1>Содержание</h1>',
            '    <ol>',
        ]
        for chapter in self.chapters:
            for label, href in chapter['toc']:
                safe_label = self._escape_xml(label)
                target = href if href else chapter['file']
                lines.append(f'      <li><a href="{target}">{safe_label}</a></li>')
        if self.converter.footnotes:
            lines.append(f'      <li><a href="notes.xhtml">Примечания</a></li>')
        lines.extend([
            '    </ol>',
            '  </nav>',
            '</body>',
            '</html>',
        ])
        return '\n'.join(lines)

    def _wrap_xhtml(self, title, content, body_style=""):
        """Обёртка контента в полный XHTML-документ."""
        style_attr = f' style="{body_style}"' if body_style else ''
        return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{self.book.lang}">
<head>
<meta charset="UTF-8"/>
<title>{self._escape_xml(title)}</title>
<link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body{style_attr}>
{content}
</body>
</html>'''

    def _escape_xml(self, text):
        """XML-экранирование."""
        if not text:
            return ''
        text = text.replace('&', '&amp;')
        text = text.replace('<', '&lt;')
        text = text.replace('>', '&gt;')
        text = text.replace('"', '&quot;')
        text = text.replace("'", '&apos;')
        return text

# Форматы обложек, которые EPUB-ридеры понимают нативно
COVER_NATIVE_FORMATS = {
    'png': 'image/png',
    'jpg': 'image/jpeg',
    'gif': 'image/gif',
    'webp': 'image/webp',
}

def _sniff_image_format(data):
    """Формат картинки по magic bytes: png/jpg/gif/webp/bmp/avif/heic/tiff или None."""
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return 'png'
    if data[:2] == b'\xff\xd8':
        return 'jpg'
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return 'gif'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'webp'
    if data[:2] == b'BM' and len(data) >= 26:
        return 'bmp'
    if data[4:8] == b'ftyp':
        blob = data[:64]
        if b'avif' in blob or b'avis' in blob:
            return 'avif'
        if any(b in blob for b in (b'heic', b'heix', b'heim', b'hevc', b'hevm', b'heis')):
            return 'heic'
    if data[:4] in (b'II*\x00', b'MM\x00*'):
        return 'tiff'
    return None

def load_cover_image(path):
    """Читает файл обложки и возвращает (data, content_type).

    PNG/JPEG/GIF/WebP возвращаются как есть — ридеры их понимают.
    Остальные форматы (AVIF, HEIC, BMP, TIFF...) конвертируются через
    Pillow в JPEG (или PNG, если есть прозрачность), так как EPUB-ридеры
    их не поддерживают.
    """
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as e:
        raise ValueError(f'не удалось прочитать файл обложки: {e}')

    fmt = _sniff_image_format(data)
    content_type = COVER_NATIVE_FORMATS.get(fmt)
    if content_type:
        w, h = _sniff_image_size(data)
        if w and h:
            return data, content_type

    try:
        from PIL import Image
    except ImportError:
        raise ValueError(
            f'формат "{fmt or "неизвестный"}" нужно конвертировать — установите Pillow: '
            'pip install Pillow')
    try:
        im = Image.open(BytesIO(data))
        im.load()
    except Exception as e:
        hint = ''
        if fmt in ('avif', 'heic'):
            hint = f' ({fmt.upper()} умеет читать Pillow 11.2+: pip install --upgrade Pillow)'
        raise ValueError(f'не удалось открыть картинку "{path.name}": {e}{hint}')

    has_alpha = im.mode in ('RGBA', 'LA') or (im.mode == 'P' and 'transparency' in im.info)
    buf = BytesIO()
    if has_alpha:
        im.convert('RGBA').save(buf, 'PNG', optimize=True)
        return buf.getvalue(), 'image/png'
    im.convert('RGB').save(buf, 'JPEG', quality=90, optimize=True)
    return buf.getvalue(), 'image/jpeg'

def attach_custom_cover(book, cover_path):
    """Ставит указанную картинку обложкой книги, заменяя штатную."""
    data, content_type = load_cover_image(cover_path)
    old_id = book.coverpage_image_id

    cover_id = 'custom-cover'
    n = 1
    while cover_id in book.binaries:
        n += 1
        cover_id = f'custom-cover{n}'
    book.binaries[cover_id] = (content_type, data)

    # Старый файл обложки больше не нужен, если на него нет ссылок в тексте
    if old_id and old_id != cover_id and old_id in book.binaries:
        referenced = set()
        for body in [book.body_element] + list(book.extra_bodies):
            if body is None:
                continue
            for el in body.iter():
                href = el.get(f'{{{XLINK_NS}}}href', '')
                if href.startswith('#'):
                    referenced.add(href[1:])
        if old_id not in referenced:
            del book.binaries[old_id]

    book.coverpage_image_id = cover_id

def has_cover(filepath):
    """Есть ли у книги обложка (coverpage/image со ссылкой на существующий binary)."""
    try:
        root = _read_fb2_root(filepath)
    except Exception:
        return False
    coverpage = fb2_find(root, 'description/title-info/coverpage')
    if coverpage is None:
        return False
    image = fb2_find(coverpage, 'image')
    if image is None:
        return False
    href = image.get(f'{{{XLINK_NS}}}href', '')
    if href.startswith('#'):
        href = href[1:]
    if not href:
        return False
    for binary in fb2_findall(root, 'binary'):
        if binary.get('id', '') == href and (binary.text or '').strip():
            return True
    return False

def convert_fb2_to_epub(input_path, output_path=None, cover_path=None):
    """
    Конвертирует FB2-файл в EPUB 3.

    cover_path — необязательный путь к своей обложке (PNG, JPEG, AVIF,
    HEIC, WebP...). Если задан, картинка становится обложкой книги
    вместо штатной.
    """
    input_path = str(input_path)
    if output_path is None:
        base = os.path.splitext(input_path)[0]
        if base.endswith('.fb2'):
            base = base[:-4]
        output_path = base + '.epub'

    print(f'Чтение: {input_path}')
    book = FB2Book()
    book.parse(input_path)
    if cover_path:
        attach_custom_cover(book, cover_path)
        binary = book.binaries[book.coverpage_image_id]
        w, h = _image_dimensions(binary[1])
        size_str = f'{w}x{h}, ' if w and h else ''
        print(f'Своя обложка: {cover_path} ({size_str}{binary[0]})')
    print(f'Название: {book.title}')
    print(f'Автор(ы): {", ".join(book.authors)}')
    print(f'Язык: {book.lang}')
    print(f'Секций: {len(book.sections)}')
    print(f'Изображений: {len(book.binaries)}')
    
    builder = EPUBBuilder(book)
    builder.build(output_path)
    return output_path

def main():
    """Точка входа CLI."""
    args = sys.argv[1:]
    cover_path = None
    positional = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ('--cover', '-c'):
            i += 1
            if i >= len(args):
                print('Ошибка: после --cover нужен путь до файла обложки')
                sys.exit(1)
            cover_path = args[i]
        elif a.startswith('--cover='):
            cover_path = a.split('=', 1)[1]
        else:
            positional.append(a)
        i += 1

    if not positional:
        print('Использование: python fb22epub.py <input.fb2> [output.epub] [--cover cover.jpg]')
        print('  --cover, -c  путь к своей обложке (PNG, JPEG, WebP, AVIF, HEIC...)')
        sys.exit(1)

    input_path = positional[0]
    output_path = positional[1] if len(positional) > 1 else None

    if not os.path.exists(input_path):
        print(f'Ошибка: файл не найден: {input_path}')
        sys.exit(1)
    if cover_path and not os.path.isfile(cover_path):
        print(f'Ошибка: обложка не найдена: {cover_path}')
        sys.exit(1)

    try:
        result = convert_fb2_to_epub(input_path, output_path, cover_path=cover_path)
        print(f'Готово!')
    except Exception as e:
        print(f'Ошибка конвертации: {e}')
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()