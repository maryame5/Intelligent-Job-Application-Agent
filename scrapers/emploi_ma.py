# scraper_emploi_ma.py
import requests
from bs4 import BeautifulSoup
import time
from urllib.parse import urljoin
import re

def extract_email_from_description(text):
    emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
    blacklist = ['noreply', 'support', 'contact', 'info']
    return [e for e in emails if not any(b in e.lower() for b in blacklist)]

class EmploiMaScraper:
    BASE_URL = "https://www.emploi.ma"

    def __init__(self):
        self.session = requests.Session()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept-Language': 'fr-FR,fr;q=0.9',
        }

    def search_jobs(self, keywords="", city="", pages=2):
        jobs = []
        query = keywords.replace(' ', '+')
        url = f"{self.BASE_URL}/recherche-jobs-maroc/{query}"
        
        try:
            resp = self.session.get(url, headers=self.headers, timeout=30)
            if resp.status_code != 200:
                return jobs
                
            soup = BeautifulSoup(resp.text, 'html.parser')
            # Emploi.ma job items
            cards = soup.select(".job-item, article.job, .job-listing, div[class*='job-']")
            
            for card in cards:
                job = self._parse_card(card)
                if job:
                    jobs.append(job)
            time.sleep(1.5)
        except Exception as e:
            print(f"Error Emploi.ma: {e}")
            
        return jobs

    def _parse_card(self, card):
        try:
            title_el = card.select_one("h2 a, h3 a, .job-title a, a.title")
            if not title_el:
                return None
            
            title = title_el.get_text(strip=True)
            link = title_el.get('href', '')
            job_url = urljoin(self.BASE_URL, link)
            
            company_el = card.select_one(".company, .employer, .firm, [class*='company']")
            company = company_el.get_text(strip=True) if company_el else "N/A"
            
            city_el = card.select_one(".location, .city, [class*='city'], [class*='location']")
            location = city_el.get_text(strip=True) if city_el else "Maroc"
            
            contract_el = card.select_one(".contract, .type, [class*='contract'], [class*='type']")
            contract = contract_el.get_text(strip=True) if contract_el else "N/A"
            
            desc_el = card.select_one(".description, .excerpt, p")
            description = desc_el.get_text(strip=True) if desc_el else ""

            return {
                'source': 'Emploi.ma',
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
        try:
            resp = self.session.get(job_url, headers=self.headers, timeout=30)
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # Selectors for description in emploi.ma
            desc = soup.select_one(".job-details, .job-content, article")
            description_text = desc.get_text(separator='\n', strip=True) if desc else ''
            
            return {
                'description': description_text,
                'emails_found': extract_email_from_description(description_text)
            }
        except Exception as e:
            return {'description': '', 'emails_found': []}
