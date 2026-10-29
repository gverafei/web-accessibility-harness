"""Backfill research features from immutable rendered HTML snapshots."""

from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from database import get_connection


AMBIGUOUS_LINK_TEXT = {
    "here", "more", "more...", "details", "more details", "link",
    "this page", "continue", "continue reading", "read more", "button",
}


def link_text(link):
    parts = [link.get_text(" ", strip=True), link.get("aria-label", "")]
    parts.extend(image.get("alt", "") for image in link.find_all("img"))
    return " ".join(part.strip() for part in parts if part and part.strip()).lower()


def is_ambiguous_link(link):
    text = " ".join(link_text(link).split())
    return "click here" in text or "click" in text or text in AMBIGUOUS_LINK_TEXT


def extract_page_features(html, url):
    soup = BeautifulSoup(html or "", "html.parser")
    host = urlsplit(url or "").hostname or ""
    host = host.lower().removeprefix("www.")
    links = soup.find_all("a", href=True)
    same_domain = 0
    skip_links = []
    for link in links:
        href = link.get("href", "")
        target = urlsplit(urljoin(url or "", href)).hostname or ""
        if target.lower().removeprefix("www.") == host:
            same_domain += 1
        if href.startswith("#") and len(href) > 1:
            skip_links.append(href[1:])
    aria_attributes = sum(
        1 for tag in soup.find_all(True) for name in tag.attrs if name.startswith("aria-")
    )
    roles = bool(soup.find(attrs={"role": True}))
    doctype = next((str(node) for node in soup.contents if node.__class__.__name__ == "Doctype"), "")
    ids = {tag.get("id") for tag in soup.find_all(id=True)}
    names = {tag.get("name") for tag in soup.find_all(attrs={"name": True})}
    return {
        "same_domain_links": same_domain,
        "visible_text_length": len(soup.get_text(" ", strip=True)),
        "aria_attributes": aria_attributes,
        "uses_aria": bool(aria_attributes or roles),
        "skip_links": len(skip_links),
        "broken_skip_links": sum(target not in ids and target not in names for target in skip_links),
        "ambiguous_links": sum(is_ambiguous_link(link) for link in links),
        "doctype": doctype,
        "valid_html5_doctype": doctype.strip().lower() == "html",
    }


def backfill(experiment_id=None):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    where = "AND experiment_id=%s" if experiment_id is not None else ""
    params = (experiment_id,) if experiment_id is not None else ()
    cursor.execute(
        f"""SELECT id,url,captured_url,source_snapshot_path FROM experiment_results
            WHERE status='completed' AND source_snapshot_path IS NOT NULL {where}""",
        params,
    )
    updated = 0
    for row in cursor.fetchall():
        path = Path(row["source_snapshot_path"])
        if not path.is_file():
            continue
        features = extract_page_features(path.read_text(encoding="utf-8", errors="replace"), row.get("captured_url") or row["url"])
        cursor.execute(
            """UPDATE experiment_results SET same_domain_links=%s,visible_text_length=%s,
               aria_attributes=%s,uses_aria=%s,skip_links=%s,broken_skip_links=%s,
               ambiguous_links=%s,doctype=%s,valid_html5_doctype=%s WHERE id=%s""",
            (*features.values(), row["id"]),
        )
        updated += 1
    conn.commit()
    cursor.close()
    conn.close()
    return updated


if __name__ == "__main__":
    import argparse
    from main import app
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", type=int)
    args = parser.parse_args()
    with app.app_context():
        print(backfill(args.experiment))
