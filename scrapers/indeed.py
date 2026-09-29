# scraper_indeed.py
from bs4 import BeautifulSoup
import time
import re
from urllib.parse import urljoin, quote_plus
import asyncio

def extract_email_from_description(text):
    if not text: return []
    emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
    blacklist = ['noreply', 'support', 'contact', 'info']
    return [e for e in emails if not any(b in e.lower() for b in blacklist)]

class IndeedScraper:
    BASE_URL = "https://ma.indeed.com"

    def __init__(self):
        # On n'initialise pas Playwright ici car il doit être utilisé de manière asynchrone
        pass

    def search_jobs(self, query, location="Maroc", pages=1):
        # Puisque main_agent.py n'est pas asynchrone, nous utilisons une boucle d'événements interne
        # ou nous utilisons sync_playwright
        from playwright.sync_api import sync_playwright
        
        jobs = []
        role_q = quote_plus(query)
        city_q = quote_plus(location)
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            
            for p_idx in range(pages):
                start = p_idx * 10
                url = f"{self.BASE_URL}/jobs?q={role_q}&l={city_q}&start={start}&fromage=7&lang=fr_MA"
                
                try:
                    print(f"    Indeed: Navigation vers {url}")
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    
                    # Attendre que les cartes d'emploi soient visibles
                    # Si rien après 5s, on passe à la suite (pas de résultats ou bloqué)
                    try:
                        page.wait_for_selector("div.job_seen_beacon", timeout=5000)
                    except:
                        print(f"    Indeed: Pas de résultats visibles sur la page {p_idx} (ou accès restreint).")
                        break # On arrête pour ce site car Indeed est souvent bloquant
                    
                    html = page.content()
                    soup = BeautifulSoup(html, "html.parser")
                    cards = soup.select("div.job_seen_beacon, .resultContent, [class*='jobsearch-SerpJobCard']")
                    
                    for card in cards:
                        job = self._parse_indeed_card(card)
                        if job:
                            jobs.append(job)
                    
                    time.sleep(2)
                except Exception as e:
                    print(f"    Indeed Error page {p_idx}: {e}")
                    # Parfois Indeed affiche un CAPTCHA ou une structure différente
                    continue
            
            browser.close()
            
        return jobs

    def _parse_indeed_card(self, card):
        try:
            title_el = card.select_one("h2 a span[title], h2 a, .jobTitle a")
            if not title_el:
                return None
            
            title = title_el.get("title") or title_el.get_text(strip=True)
            link_el = card.select_one("h2 a")
            job_url = urljoin(self.BASE_URL, link_el.get("href", "")) if link_el else None
            
            company_el = card.select_one("[data-testid='company-name'], .companyName, span.company")
            company = company_el.get_text(strip=True) if company_el else "N/A"
            
            location_el = card.select_one("[data-testid='text-location'], .companyLocation, .location")
            location = location_el.get_text(strip=True) if location_el else "Maroc"
            
            salary_el = card.select_one(".salary-snippet-container, .attribute_snippet, [class*='salary']")
            salary = salary_el.get_text(strip=True) if salary_el else "N/A"
            
            desc_el = card.select_one(".job-snippet, .summary, ul")
            description = desc_el.get_text(strip=True) if desc_el else ""

            return {
                'source': 'Indeed',
                'job_title': title,
                'company_name': company,
                'location': location,
                'salary': salary,
                'description': description,
                'job_url': job_url,
                'date_scraped': time.strftime('%Y-%m-%d %H:%M:%S'),
                'status': 'New'
            }
        except:
            return None

    def get_job_details(self, job_url):
        from playwright.sync_api import sync_playwright
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                )
                page = context.new_page()
                page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
                try:
                    page.wait_for_selector("#jobDescriptionText", timeout=5000)
                except:
                    pass
                html = page.content()
                soup = BeautifulSoup(html, "html.parser")
                desc_el = soup.select_one("#jobDescriptionText")
                description_text = desc_el.get_text(separator='\n', strip=True) if desc_el else ""
                browser.close()
                return {
                    'description': description_text,
                    'emails_found': extract_email_from_description(description_text)
                }
        except Exception as e:
            return {'description': '', 'emails_found': []}