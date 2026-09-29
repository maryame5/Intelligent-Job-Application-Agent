# scraper_bayt.py
from bs4 import BeautifulSoup
import time
from urllib.parse import urljoin
import re

def extract_email_from_description(text):
    if not text: return []
    emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
    blacklist = ['noreply', 'support', 'contact', 'info']
    return [e for e in emails if not any(b in e.lower() for b in blacklist)]

class BaytScraper:
    BASE_URL = "https://www.bayt.com"

    def __init__(self):
        pass

    def search_jobs(self, keywords="", city="Morocco", pages=1):
        from playwright.sync_api import sync_playwright
        
        jobs = []
        role_q = keywords.lower().replace(" ", "-")
        city_q = city.lower().replace(" ", "-")
        url = f"{self.BASE_URL}/en/morocco/jobs/{role_q}-jobs-in-{city_q}/"
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            
            try:
                print(f"    Bayt: Navigation vers {url}")
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                
                # Attendre un peu que les résultats apparaissent
                # Si rien ne vient après 5s, on considère qu'il n'y a pas d'offres
                try:
                    page.wait_for_selector("li[class*='has-pointer-d'], .media.u-stretch", timeout=5000)
                except:
                    print("    Bayt: Aucune offre trouvée ou chargement lent.")
                    browser.close()
                    return []
                
                html = page.content()
                soup = BeautifulSoup(html, "html.parser")
                cards = soup.select("li[class*='has-pointer-d'], .media.u-stretch")
                
                for card in cards:
                    job = self._parse_card(card)
                    if job:
                        jobs.append(job)
                
            except Exception as e:
                print(f"    Bayt.com Error: {e}")
                
            browser.close()
            
        return jobs

    def _parse_card(self, card):
        try:
            title_el = card.select_one("h2 a, h3 a, [class*='jb-job-title'], b a")
            if not title_el:
                return None
            
            title = title_el.get_text(strip=True)
            link = title_el.get('href', '')
            job_url = urljoin(self.BASE_URL, link)
            
            company_el = card.select_one("[class*='jb-company'], .t-default")
            company = company_el.get_text(strip=True) if company_el else "N/A"
            
            city_el = card.select_one("[class*='jb-loc'], [class*='location']")
            location = city_el.get_text(strip=True) if city_el else "Maroc"
            
            contract_el = card.select_one("[class*='jb-type'], [class*='type']")
            contract = contract_el.get_text(strip=True) if contract_el else "N/A"
            
            desc_el = card.select_one("[class*='jb-desc'], p")
            description = desc_el.get_text(strip=True) if desc_el else ""

            return {
                'source': 'Bayt.com',
                'job_title': title,
                'company_name': company,
                'location': location,
                'contract_type': contract,
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
                html = page.content()
                soup = BeautifulSoup(html, "html.parser")
                desc_el = soup.select_one(".t-regular.m10b, .is-rendered")
                description_text = desc_el.get_text(separator='\n', strip=True) if desc_el else ""
                browser.close()
                return {
                    'description': description_text,
                    'emails_found': extract_email_from_description(description_text)
                }
        except Exception as e:
            return {'description': '', 'emails_found': []}
