from app.publishers.notion import markdown_to_blocks


def _types(blocks):
    return [b["type"] for b in blocks]


def test_headings_and_paragraphs():
    md = "# Title\n\n## Section\n\nSome paragraph text.\n\n### Sub"
    blocks = markdown_to_blocks(md)
    assert _types(blocks) == ["heading_1", "heading_2", "paragraph", "heading_3"]


def test_lists_quotes_dividers():
    md = "- one\n- two\n1. first\n2. second\n> quoted\n---"
    blocks = markdown_to_blocks(md)
    assert _types(blocks) == [
        "bulleted_list_item", "bulleted_list_item",
        "numbered_list_item", "numbered_list_item",
        "quote", "divider",
    ]
    assert blocks[2]["numbered_list_item"]["rich_text"][0]["text"]["content"] == "first"


def test_code_fence():
    md = "```python\nprint('hi')\nx = 1\n```"
    blocks = markdown_to_blocks(md)
    assert blocks[0]["type"] == "code"
    assert blocks[0]["code"]["language"] == "python"
    assert "print('hi')\nx = 1" == blocks[0]["code"]["rich_text"][0]["text"]["content"]


def test_inline_bold_and_link():
    blocks = markdown_to_blocks("This is **bold** and a [link](https://e.co).")
    rich = blocks[0]["paragraph"]["rich_text"]
    bold = [r for r in rich if r.get("annotations", {}).get("bold")]
    assert bold and bold[0]["text"]["content"] == "bold"
    links = [r for r in rich if r["text"].get("link")]
    assert links and links[0]["text"]["link"]["url"] == "https://e.co"


def test_long_text_split_at_2000():
    blocks = markdown_to_blocks("x" * 4500)
    rich = blocks[0]["paragraph"]["rich_text"]
    assert [len(r["text"]["content"]) for r in rich] == [2000, 2000, 500]


def test_empty_lines_skipped():
    assert markdown_to_blocks("\n\n\n") == []
