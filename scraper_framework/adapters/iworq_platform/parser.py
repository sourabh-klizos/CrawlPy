from bs4 import BeautifulSoup


def parse_page(soup: BeautifulSoup) -> dict[str, str | None]:
    title = soup.title.get_text(strip=True) if soup.title else None
    body_text = " ".join(soup.get_text(" ", strip=True).split())
    description = title or body_text or None
    return {"title": title, "description": description}
