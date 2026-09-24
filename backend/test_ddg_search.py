import httpx
from bs4 import BeautifulSoup

def search_tksr():
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    urls = [
        "https://html.duckduckgo.com/html/?q=TKSR+Product+Services+director+OR+founder",
        "https://html.duckduckgo.com/html/?q=Garware+Technical+Fibres+directors+board",
        "https://html.duckduckgo.com/html/?q=Vardhman+Textiles+directors+board",
    ]
    for u in urls:
        print("Searching:", u)
        try:
            r = httpx.get(u, headers=headers, timeout=10)
            soup = BeautifulSoup(r.text, 'html.parser')
            snippets = soup.find_all('a', class_='result__snippet')
            for s in snippets[:3]:
                print("  SNIPPET:", s.get_text(strip=True))
        except Exception as e:
            print("  Error:", e)

if __name__ == '__main__':
    search_tksr()
