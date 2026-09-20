#!/usr/bin/env python3
"""Interactive FB2 to EPUB 3 converter.

Lets you pick a specific .fb2/.zip file from the input folder and
convert it to the output folder.
"""
import os
import sys
from pathlib import Path

from fb22epub import convert_fb2_to_epub

SUPPORTED_EXTENSIONS = ('.fb2', '.zip')

def find_input_files(input_dir):
    files = []
    for entry in sorted(input_dir.iterdir()):
        if entry.is_file() and entry.suffix.lower() in SUPPORTED_EXTENSIONS:
            files.append(entry)
    return files

def output_name(input_file):
    name = input_file.stem
    if name.lower().endswith('.fb2'):
        name = name[:-4]
    return name + '.epub'

def list_files(files):
    print('Files in input/:')
    if not files:
        print('  (no .fb2 or .zip files found)')
    for i, f in enumerate(files, 1):
        print(f'  {i}. {f.name}')

def pick_file(files):
    while True:
        choice = input('\nEnter file number (or path, or q to quit): ').strip().strip('"')
        if not choice:
            continue
        if choice.lower() in ('q', 'quit', 'exit'):
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(files):
            return files[int(choice) - 1]
        path = Path(choice)
        if path.is_file():
            return path
        print(f'Not found: {choice}')

def main():
    input_dir = Path('input')
    output_dir = Path('output')
    input_dir.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)

    while True:
        files = find_input_files(input_dir)
        list_files(files)
        if not files:
            print(f'\nPut .fb2 or .zip files into: {input_dir.resolve()}')
            if input('\nExit? (y/N): ').strip().lower() in ('y', 'yes'):
                return
            continue

        src = pick_file(files)
        if src is None:
            return
        dst = output_dir / output_name(src)
        try:
            convert_fb2_to_epub(src, dst)
            print(f'\nDone: {src.name} -> {dst.name}')
        except Exception as e:
            print(f'\nConversion failed for {src.name}: {e}')

        print('Returning to file list...\n')

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)