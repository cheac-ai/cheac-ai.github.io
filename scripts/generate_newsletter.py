#!/usr/bin/env python3
"""
Generate an email-ready HTML newsletter alert for a Quarto (.qmd) article
or a standalone announcement markdown (.md) file.

Usage:
    python scripts/generate_newsletter.py <path-to-post.qmd> [options]
    python scripts/generate_newsletter.py --launch [options]
    python scripts/generate_newsletter.py _email/launch.md [options]

Options:
    --launch          Generate the launch announcement for the CHEAC \\btw channel
    --intro TEXT      Custom introductory message / greeting
    --topic TEXT      Specific topic name to emphasize in generated teaser
    --copy            Copy formatted HTML directly to Windows clipboard for Outlook
    --open            Open the resulting HTML file in your default web browser
    --out DIR         Output directory (default: _email)

Example:
    python scripts/generate_newsletter.py --launch --copy
    python scripts/generate_newsletter.py practices/agent-instructions.qmd --copy --open
"""

import argparse
import ctypes
from ctypes import wintypes
import logging
import os
import re
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

# Suppress benign cssutils vendor-prefix warning spam
import cssutils
cssutils.log.setLevel(logging.ERROR)

import markdown
import premailer
import yaml


DEFAULT_LAUNCH_CONTENT = """---
title: "Launching CHEAC \\\\btw: AI in Research"
tag: "ANNOUNCEMENT"
link: "https://cheac-ai.github.io"
button-text: "Explore CHEAC \\\\btw &rarr;"
author: "CHEAC AI Council"
---

Dear CHEAC colleagues,

We are excited to announce the launch of **CHEAC \\\\btw**, an advisory channel and living community resource dedicated to discussing artificial intelligence in research across CHEAC (University of Copenhagen and University of Bern).

### Advisory mandate
AI tools are rapidly reshaping scientific workflows, programming, literature discovery, and data management. The CHEAC AI Council provides advisory guidance to empower researchers, explore workflows, and safeguard scientific integrity. We do not act as an enforcement body—our purpose is to share practical knowledge and support researchers across our groups.

### What you will find on the site:
- **Best Practices**: Practical guides on AI agents, starting prompt templates, and coding workflows.
- **Guidelines**: KU guidelines on AI usage and the official CHEAC Data Management Plan.
- **AI in Research**: Insights on how machine learning and foundation models impact chemistry and materials science.
- **Transparency**: Guidance on how to document AI usage responsibly in papers, code, and figures.
- **Suggestion Box**: Topics the council should investigate next—open an issue to share your ideas!

Everyone at CHEAC is invited to explore the site, test the workflows, and contribute suggestions.
"""


def find_project_root() -> Path:
    """Find repository root by looking for _quarto.yml."""
    current = Path.cwd().resolve()
    for p in [current, *current.parents]:
        if (p / "_quarto.yml").is_file():
            return p
    return current


def load_quarto_config(root: Path) -> dict:
    """Load _quarto.yml if present."""
    config_file = root / "_quarto.yml"
    if config_file.is_file():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"[Warning] Could not parse _quarto.yml: {e}")
    return {}


def parse_frontmatter(file_path: Path) -> tuple[dict, str]:
    """Extract YAML frontmatter and body markdown from a file."""
    content = file_path.read_text(encoding="utf-8")
    pattern = r"^---\s*\n(.*?)\n---\s*\n(.*)$"
    match = re.search(pattern, content, flags=re.DOTALL)
    if not match:
        raise ValueError(f"No YAML frontmatter found in {file_path}")
    frontmatter_raw = match.group(1)
    body_raw = match.group(2)
    data = yaml.safe_load(frontmatter_raw) or {}
    return data, body_raw


def clean_quarto_text(text: str) -> str:
    """Remove or resolve Quarto shortcodes, markdown links, and formatting."""
    if not text:
        return ""
    text = re.sub(r"\{\{<\s*cheac\s*>}}", "CHEAC", text)
    text = re.sub(r"\{\{<[^>]+>}}", "", text)
    text = re.sub(r"\[@[^\]]+\]", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    return text.strip()


def extract_body_synopsis(body_raw: str) -> str:
    """Extract first paragraph of actual text from the markdown body."""
    lines = body_raw.splitlines()
    para_lines = []
    in_para = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_para:
                break
            continue
        if stripped.startswith("#") or stripped.startswith(":::") or stripped.startswith("![]") or stripped.startswith("<"):
            if in_para:
                break
            continue
        in_para = True
        para_lines.append(stripped)

    synopsis = " ".join(para_lines)
    return clean_quarto_text(synopsis)


def format_date(date_val) -> str:
    """Format date to 'D MMM YYYY' matching site style."""
    if not date_val:
        return datetime.now().strftime("%d %b %Y")
    if isinstance(date_val, datetime):
        return date_val.strftime("%d %b %Y")
    if hasattr(date_val, "strftime"):
        return date_val.strftime("%d %b %Y")
    date_str = str(date_val).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%d %b %Y")
        except ValueError:
            pass
    return date_str


def format_authors(author_val) -> tuple[str, str]:
    """
    Format author data.
    Returns:
        (author_names, author_display_line)
    """
    if not author_val:
        return "The CHEAC Team", "CHEAC AI Council"

    names = []
    lines = []

    if isinstance(author_val, str):
        clean_name = clean_quarto_text(author_val)
        return clean_name, clean_name

    if isinstance(author_val, dict):
        author_val = [author_val]

    if isinstance(author_val, list):
        for item in author_val:
            if isinstance(item, str):
                name = clean_quarto_text(item)
                names.append(name)
                lines.append(name)
            elif isinstance(item, dict):
                name = clean_quarto_text(item.get("name", ""))
                affil = clean_quarto_text(item.get("affiliation", ""))
                if name:
                    names.append(name)
                    if affil:
                        lines.append(f"{name} ({affil})")
                    else:
                        lines.append(name)

    names_str = ", ".join(names) if names else "CHEAC Contributor"
    display_str = " &middot; ".join(lines) if lines else names_str
    return names_str, display_str


def get_section_tag(rel_path: Path) -> str:
    """Determine category label from folder name."""
    parts = rel_path.parts
    if len(parts) > 1:
        folder = parts[0].lower()
        mapping = {
            "practices": "Best Practices",
            "guidelines": "Guidelines",
            "news": "AI News",
            "ai-in-research": "AI in Research",
            "transparency": "Transparency",
            "suggestions": "Suggestions",
            "contributing": "Contributing",
            "_email": "Announcement",
        }
        return mapping.get(folder, folder.replace("-", " ").title())
    return "CHEAC Announcement"


def set_clipboard_html(html_fragment: str, plain_text: str = "") -> bool:
    """Place HTML format on the Windows clipboard (CF_HTML)."""
    if sys.platform != "win32":
        print("[Notice] Direct OS clipboard injection is only supported on Windows.")
        return False

    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32

    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]

    user32.RegisterClipboardFormatW.restype = wintypes.UINT
    user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.CloseClipboard.restype = wintypes.BOOL

    CF_HTML = user32.RegisterClipboardFormatW("HTML Format")
    if not CF_HTML:
        return False

    header_template = (
        "Version:0.9\r\n"
        "StartHTML:{:010d}\r\n"
        "EndHTML:{:010d}\r\n"
        "StartFragment:{:010d}\r\n"
        "EndFragment:{:010d}\r\n"
    )
    doc_prefix = "<html>\r\n<body>\r\n<!--StartFragment-->"
    doc_suffix = "<!--EndFragment-->\r\n</body>\r\n</html>"

    dummy_header = header_template.format(0, 0, 0, 0)
    header_len = len(dummy_header.encode("utf-8"))
    prefix_len = len(doc_prefix.encode("utf-8"))
    frag_len = len(html_fragment.encode("utf-8"))
    suffix_len = len(doc_suffix.encode("utf-8"))

    start_html = header_len
    start_frag = header_len + prefix_len
    end_frag = start_frag + frag_len
    end_html = end_frag + suffix_len

    final_header = header_template.format(start_html, end_html, start_frag, end_frag)
    full_html = final_header + doc_prefix + html_fragment + doc_suffix
    html_bytes = full_html.encode("utf-8") + b"\x00"

    GMEM_MOVEABLE = 0x0002

    if not user32.OpenClipboard(0):
        return False
    try:
        user32.EmptyClipboard()
        # Set HTML
        h_mem_html = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(html_bytes))
        p_mem_html = kernel32.GlobalLock(h_mem_html)
        ctypes.memmove(p_mem_html, html_bytes, len(html_bytes))
        kernel32.GlobalUnlock(h_mem_html)
        user32.SetClipboardData(CF_HTML, h_mem_html)

        # Set plain text fallback
        if plain_text:
            CF_UNICODETEXT = 13
            text_bytes = (plain_text + "\x00").encode("utf-16le")
            h_mem_txt = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(text_bytes))
            p_mem_txt = kernel32.GlobalLock(h_mem_txt)
            ctypes.memmove(p_mem_txt, text_bytes, len(text_bytes))
            kernel32.GlobalUnlock(h_mem_txt)
            user32.SetClipboardData(CF_UNICODETEXT, h_mem_txt)
        return True
    except Exception as e:
        print(f"[Error] Failed to copy to clipboard: {e}")
        return False
    finally:
        user32.CloseClipboard()


def generate_newsletter(
    file_path: Path,
    intro_override: str | None = None,
    topic: str | None = None,
    output_dir: Path | None = None,
    copy_to_clipboard: bool = False,
    open_in_browser: bool = False,
) -> Path:
    root = find_project_root()
    quarto_cfg = load_quarto_config(root)
    site_url = quarto_cfg.get("website", {}).get("site-url", "https://cheac-ai.github.io").rstrip("/")

    data, body_raw = parse_frontmatter(file_path)

    # Determine if this is a standalone announcement draft or a published article .qmd
    is_standalone = file_path.suffix.lower() == ".md" or "link" in data or data.get("tag") == "ANNOUNCEMENT"

    # Title
    title = clean_quarto_text(data.get("pagetitle") or data.get("title", "CHEAC AI Council Announcement"))

    # Author
    author_names, author_display = format_authors(data.get("author", "CHEAC AI Council" if is_standalone else None))

    # Date
    date_formatted = format_date(data.get("date"))

    # URL and button text
    if "link" in data:
        post_url = data["link"]
    elif is_standalone:
        post_url = site_url
    else:
        rel_path = file_path.resolve().relative_to(root.resolve())
        html_rel_path = rel_path.with_suffix(".html").as_posix()
        post_url = f"{site_url}/{html_rel_path}"

    button_text = clean_quarto_text(data.get("button-text", "Explore CHEAC \\btw &rarr;" if is_standalone else "Read the post &rarr;"))

    # Section / tag
    if "tag" in data:
        section_tag = clean_quarto_text(data["tag"])
    else:
        rel_path = file_path.resolve().relative_to(root.resolve())
        section_tag = get_section_tag(rel_path)

    # Image
    image_block = ""
    raw_image = data.get("image")
    if raw_image:
        raw_image_str = str(raw_image).strip()
        if raw_image_str.startswith("http://") or raw_image_str.startswith("https://"):
            resolved_img_url = raw_image_str
        else:
            rel_path = file_path.resolve().relative_to(root.resolve())
            post_folder = rel_path.parent
            img_rel = (post_folder / raw_image_str).resolve()
            try:
                img_from_root = img_rel.relative_to(root.resolve()).as_posix()
                resolved_img_url = f"{site_url}/{img_from_root}"
            except ValueError:
                resolved_img_url = f"{site_url}/{raw_image_str.lstrip('/')}"

        image_alt = clean_quarto_text(data.get("image-alt", title))
        image_block = (
            f'<div class="post-image">'
            f'<img src="{resolved_img_url}" alt="{image_alt}" width="554">'
            f'</div>'
        )

    # Body / description
    if is_standalone:
        # For standalone announcements, convert markdown body to styled HTML
        description = markdown.markdown(body_raw.strip(), extensions=["extra"])
    else:
        raw_desc = data.get("description") or data.get("subtitle")
        if raw_desc:
            description = clean_quarto_text(str(raw_desc))
        else:
            description = extract_body_synopsis(body_raw)

    # Intro text
    if intro_override:
        paragraphs = [p.strip() for p in intro_override.split("\n\n") if p.strip()]
        intro_html = "".join(f"<p>{p}</p>" for p in paragraphs)
    elif is_standalone:
        # If it's a standalone announcement, body already contains the greeting
        intro_html = ""
    else:
        topic_text = topic or title
        intro_html = (
            f"<p>Hi everyone,</p>"
            f"<p><strong>{author_names}</strong> wrote a new post about <strong>{topic_text}</strong>. "
            f"Here is a short synopsis from the CHEAC site:</p>"
        )

    intro_section = (
        f'<tr>\n            <td class="intro-cell">\n              {intro_html}\n            </td>\n          </tr>\n'
        if intro_html
        else ""
    )

    preheader_text = data.get("preheader") or f"{title} — {site_url}"

    # Load master template
    template_path = root / "assets" / "templates" / "email-newsletter.html"
    if not template_path.is_file():
        raise FileNotFoundError(f"Template not found at {template_path}")

    template_content = template_path.read_text(encoding="utf-8")

    # Replace placeholders
    rendered = (
        template_content
        .replace("{{POST_TITLE}}", title)
        .replace("{{POST_URL}}", post_url)
        .replace("{{AUTHOR_LINE}}", author_display)
        .replace("{{DATE}}", date_formatted)
        .replace("{{DESCRIPTION}}", description)
        .replace("{{IMAGE_BLOCK}}", image_block)
        .replace("{{SECTION_TAG}}", section_tag)
        .replace("{{INTRO_SECTION}}", intro_section)
        .replace("{{BUTTON_TEXT}}", button_text)
        .replace("{{SITE_URL}}", site_url)
        .replace("{{PREHEADER}}", preheader_text)
    )

    # Run premailer to inline CSS and ensure absolute URLs
    inlined_html = premailer.transform(
        rendered,
        base_url=site_url,
        keep_style_tags=True,
        strip_important=False,
    )

    # Determine output path
    if output_dir is None:
        output_dir = root / "_email"
    output_dir.mkdir(parents=True, exist_ok=True)

    slug = file_path.stem
    out_file = output_dir / f"{slug}.html"
    out_file.write_text(inlined_html, encoding="utf-8")

    print(f"[Success] Generated email file: {out_file}")
    print(f"  - Title:   {title}")
    print(f"  - Tag:     {section_tag}")
    print(f"  - Link:    {post_url}")

    # Copy to clipboard if requested
    if copy_to_clipboard:
        plain_text = f"{title}\n\n{post_url}"
        if set_clipboard_html(inlined_html, plain_text):
            print("\n[Clipboard] Successfully copied email HTML to clipboard!")
            print("            -> Switch to Outlook Web and press Ctrl + V in the email body.")
        else:
            print("[Warning] Could not copy directly to clipboard. You can open the file and copy from browser.")

    # Open in browser if requested
    if open_in_browser:
        print(f"\n[Browser] Opening {out_file.name} in default browser...")
        webbrowser.open_new_tab(out_file.as_uri())

    return out_file


def main():
    parser = argparse.ArgumentParser(
        description="Generate an email-ready HTML newsletter from a Quarto (.qmd) article or standalone markdown (.md) announcement."
    )
    parser.add_argument("post", nargs="?", default=None, help="Path to .qmd article or .md draft")
    parser.add_argument("--launch", action="store_true", help="Generate the launch announcement for CHEAC \\btw channel")
    parser.add_argument("--intro", type=str, default=None, help="Custom intro message / greeting")
    parser.add_argument("--topic", type=str, default=None, help="Topic description for the announcement text")
    parser.add_argument("--out", type=str, default="_email", help="Output directory (default: _email)")
    parser.add_argument("--copy", action="store_true", help="Copy email HTML to Windows clipboard (ready for Ctrl+V in Outlook)")
    parser.add_argument("--open", action="store_true", help="Open generated HTML in browser")

    args = parser.parse_args()

    root = find_project_root()

    if args.launch:
        launch_file = root / "_email" / "launch.md"
        launch_file.parent.mkdir(parents=True, exist_ok=True)
        if not launch_file.is_file():
            launch_file.write_text(DEFAULT_LAUNCH_CONTENT, encoding="utf-8")
        target_file = launch_file
    elif args.post:
        target_file = Path(args.post)
        if not target_file.is_file():
            alt_path = root / args.post
            if alt_path.is_file():
                target_file = alt_path
            else:
                print(f"Error: Could not find file: {args.post}", file=sys.stderr)
                sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)

    out_dir = Path(args.out)
    generate_newsletter(
        file_path=target_file,
        intro_override=args.intro,
        topic=args.topic,
        output_dir=out_dir,
        copy_to_clipboard=args.copy,
        open_in_browser=args.open,
    )


if __name__ == "__main__":
    main()
