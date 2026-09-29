"""Keep-alive visit for the Streamlit Community Cloud app.

Loads the app in headless Chromium and waits for the dashboard title,
which only renders once the Streamlit app has hydrated. A real browser
pass counts as genuine traffic (this is what resets the 7-day sleep
timer). Plain curl does NOT work: Streamlit's edge bot gate answers every
automated HTTP client with 303 -> share.streamlit.io/-/auth, so a curl
"ping" never reaches the app container.

Run by .github/workflows/keep_alive.yml every 2 days.
"""

from playwright.sync_api import sync_playwright

URL = "https://us-market-sentiment.streamlit.app/"
TITLE_TEXT = "US Market Sentiment"


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        # domcontentloaded, not networkidle: Streamlit holds a websocket
        # open, so the network is never fully idle.
        page.goto(URL, wait_until="domcontentloaded", timeout=180_000)
        page.get_by_text(TITLE_TEXT, exact=False).first.wait_for(timeout=120_000)
        print("app loaded: title present, keep-alive visit counted")
        browser.close()


if __name__ == "__main__":
    main()
