from neuro_mvp.web_search_tool import _clean_text, pack_for_context


def test_clean_text_strips_scripts_and_tags():
    html = """
    <html><head><style>h1{color:red;}</style><script>console.log('hi');</script></head>
    <body><h1>Hello</h1><p>World</p></body></html>
    """
    text = _clean_text(html)
    assert 'console.log' not in text
    assert '<h1>' not in text
    assert 'Hello' in text


def test_pack_for_context_limits_results():
    payload = {
        'results': [
            {'title': 'First', 'url': 'https://a', 'content': 'A' * 10},
            {'title': 'Second', 'url': 'https://b', 'content': 'B' * 10},
            {'title': 'Third', 'url': 'https://c', 'content': 'C' * 10},
        ]
    }
    packed = pack_for_context(payload, max_pages=2, per_page_chars=5)
    sections = packed.split('\n\n---\n\n')
    assert len(sections) == 2
    assert 'First' in sections[0]
    assert 'Second' in sections[1]
    assert 'AAAAA' in sections[0]
