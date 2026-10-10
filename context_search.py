import os
from tinyfish import TinyFish

# In the terminal, before running app.py:   set TINYFISH_API_KEY=your_key
_tf = TinyFish() if os.environ.get("TINYFISH_API_KEY") else None


def context(query):
    """Search the web for the caption/claim that came with an image."""
    query = (query or "").strip()
    if not query:
        return {"results": [], "error": "No caption or claim given."}
    if _tf is None:
        return {"results": [], "error": "TINYFISH_API_KEY is not set on the server."}
    try:
        resp = _tf.search.query(query=query)
        return {"results": [{
            "title": r.title or "",
            "url": r.url or "",
            "site": r.site_name or "",
            "snippet": r.snippet or "",
        } for r in resp.results[:6]]}
    except Exception as e:
        return {"results": [], "error": str(e)}
