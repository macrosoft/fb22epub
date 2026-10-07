# fb22epub

Convert FictionBook (FB2) e-books to EPUB 3 format with a single Python script.

- No external dependencies required — works with the Python standard library.
- Optional `lxml` and `Pillow` for better performance and image handling.
- Preserves metadata, chapter structure, formatting, and images.

## Features

- **EPUB 3 output**: valid EPUB 3 package (OPF, XHTML content documents, `nav.xhtml` TOC, `container.xml`).
- **Zero dependencies**: pure standard library baseline; `lxml` (faster parsing) and `Pillow` (image dimensions) are used only if installed.
- **Metadata**: title, authors, language, genre, date, publisher, ISBN, and series name/number are carried over into the OPF metadata.
- **Cover**: creates a cover page with an SVG wrapper that preserves the image aspect ratio; marks the cover in the manifest with `cover-image`. You can also attach your own cover image (even when the book has none).
- **Images**: embedded and binary-linked images are extracted to `images/`; when duplicate ids exist, the highest-quality copy wins.
- **Image dimension sniffing** without Pillow: built-in parsers for PNG, GIF, JPEG, WebP, and BMP.
- **Structure**: chapters, sub-chapters, epigraphs, annotations, poems, quotes, tables, code blocks, subtitles, and notes (footnotes) are converted to styled XHTML.
- **Chapter splitting**: every titled section up to the second nesting level becomes its own XHTML file; deeper sections stay inline as `h3`–`h6`. Sections whose title is just a number (e.g. the letters `1`, `2`) are never split out. Heading-only parts ("Part One", "Book Two") are transparent — they don't count toward the nesting depth, so chapters nested inside them (roman → part → chapter) still get their own files.
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
python fb22epub.py <input.fb2> [output.epub] [--cover <image>]
```

`--cover` / `-c` sets your own cover image. PNG, JPEG, GIF, and WebP are embedded as-is;
AVIF, HEIC, BMP, TIFF, and anything else Pillow can open are converted to JPEG
(PNG when the image has transparency), because EPUB readers don't support those formats.
AVIF/HEIC decoding requires Pillow 11.2+ (`pip install --upgrade Pillow`).
If the book already had a cover, it is replaced (and dropped from the output unless
it is also used inside the text).

If `output.epub` is omitted, the output is written next to the input with the same name and a `.epub` extension.

The input can also be a `.zip` archive containing an FB2 file.

## Interactive selector

Pick a specific file from the `input/` folder and convert it to `output/`:

```bash
python convert.py
```

The tool lists all `.fb2`/`.zip` files found in `input/` (created automatically on first run). Enter a file number to convert it, or type a path to a file anywhere. After each conversion it returns to the list; type `q` to quit.

If the selected book has no cover, the tool offers to point at an image file to use as
a cover (PNG, JPEG, AVIF, WebP... — the path can be pasted with quotes, e.g. dragged
from Explorer). If the book already has a cover, it offers to replace it. Press Enter to
skip. Invalid or unreadable images are rejected right away with a reason, so you can try
another file.

## As a script

```python
from fb22epub import convert_fb2_to_epub

convert_fb2_to_epub("book.fb2", "book.epub")
convert_fb2_to_epub("book.fb2", "book.epub", cover_path="cover.avif")
```

There are also helpers: `has_cover("book.fb2")` returns whether the book has a cover,
and `load_cover_image("cover.avif")` loads/converts an image to an EPUB-friendly format
without converting the book.

## Examples

```bash
python fb22epub.py "book.fb2"
python fb22epub.py "book.fb2.zip"
python fb22epub.py "in.fb2" "out.epub"
```