# fb22epub

Convert FictionBook (FB2) e-books to EPUB 3 format with a single Python script.

- No external dependencies required — works with the Python standard library.
- Optional `lxml` and `Pillow` for better performance and image handling.
- Preserves metadata, chapter structure, formatting, and images.

## Features

- **EPUB 3 output**: valid EPUB 3 package (OPF, XHTML content documents, `nav.xhtml` TOC, `container.xml`).
- **Zero dependencies**: pure standard library baseline; `lxml` (faster parsing) and `Pillow` (image dimensions) are used only if installed.
- **Metadata**: title, authors, language, genre, date, publisher, ISBN, and series name/number are carried over into the OPF metadata.
- **Cover**: creates a cover page with an SVG wrapper that preserves the image aspect ratio; marks the cover in the manifest with `cover-image`.
- **Images**: embedded and binary-linked images are extracted to `images/`; when duplicate ids exist, the highest-quality copy wins.
- **Image dimension sniffing** without Pillow: built-in parsers for PNG, GIF, JPEG, WebP, and BMP.
- **Structure**: chapters, sub-chapters, epigraphs, annotations, poems, quotes, tables, code blocks, subtitles, and notes (footnotes) are converted to styled XHTML.
- **Chapter splitting**: every titled section up to the second nesting level becomes its own XHTML file; deeper sections stay inline as `h3`–`h6`. Sections whose title is just a number (e.g. the letters `1`, `2`) are never split out.
- **Flat TOC**: `nav.xhtml` lists every chapter file in document order. A part that has no text of its own (only a heading plus chapters) does not get a file — its heading is printed at the top of its first chapter and linked from the TOC via an anchor.
- **Footnote support**: `notes.xhtml` endnotes page with `epub:type` markup and `noteref` links.
- **Frontmatter**: sections without a title at the beginning of the book (title page, copyright, annotation) are placed in frontmatter.
- **Style**: included `style.css` for a reader-friendly layout.

## Requirements

- Python 3.6+

Optional, for improved parsing and image handling:

```bash
pip install lxml Pillow
```

## Usage

```bash
python fb22epub.py <input.fb2> [output.epub]
```

If `output.epub` is omitted, the output is written next to the input with the same name and a `.epub` extension.

The input can also be a `.zip` archive containing an FB2 file.

## Interactive selector

Pick a specific file from the `input/` folder and convert it to `output/`:

```bash
python convert.py
```

The tool lists all `.fb2`/`.zip` files found in `input/` (created automatically on first run). Enter a file number to convert it, or type a path to a file anywhere. After each conversion it returns to the list; type `q` to quit.

## As a script

```python
from fb22epub import convert_fb2_to_epub

convert_fb2_to_epub("book.fb2", "book.epub")
```

## Examples

```bash
python fb22epub.py "book.fb2"
python fb22epub.py "book.fb2.zip"
python fb22epub.py "in.fb2" "out.epub"
```