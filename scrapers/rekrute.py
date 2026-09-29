# scraper_rekrute.py
import requests
from bs4 import BeautifulSoup
import time
import re

def extract_email_from_description(text):
    emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
    blacklist = ['noreply', 'support', 'contact', 'info']
    return [e for e in emails if not any(b in e for b in blacklist)]

class RekruteScraper:
    BASE_URL = "https://www.rekrute.com"

    def __init__(self):
        self.session = requests.Session()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Accept-Language': 'fr-FR,fr;q=0.9',
        }

    def search_jobs(self, keywords="", city="", sector="", pages=2):
        jobs = []
        query = keywords.replace(' ', '+')
        for page in range(1, pages + 1):
            # Rekrute URL pattern
            search_url = f"{self.BASE_URL}/offres-emploi-maroc.html?s={query}&p={page}"
            if city:
                search_url += f"&c={city}"
            
            try:
                resp = self.session.get(search_url, headers=self.headers, timeout=30)
                if resp.status_code != 200:
                    continue
                soup = BeautifulSoup(resp.text, 'html.parser')
                
                # Use more robust selector for job items
                job_items = soup.select("li[class*='post-id']")
                if not job_items:
                    # Fallback to general cards
                    job_items = soup.find_all('div', class_=['postuler', 'job-item', 'offre-emploi'])
                
                for item in job_items:
                    job = self._parse_rekrute_item(item)
                    if job:
                        jobs.append(job)
                time.sleep(1.5)
            except Exception as e:
                print(f"Error Rekrute page {page}: {e}")
                continue
        return jobs

    def _parse_rekrute_item(self, item):
        try:
            # Better selectors based on current Rekrute layout
            title_el = item.select_one("a.titreJob, h2 a, .job-title a")
            if not title_el:
                return None
            
            title = title_el.get_text(strip=True)
            link = title_el.get('href', '')
            job_url = self.BASE_URL + link if link.startswith('/') else link
            
            company_el = item.select_one(".recruteur, .company-name, span.name")
            company = company_el.get_text(strip=True) if company_el else "N/A"
            
            city_el = item.select_one(".location, .ville, [class*='city']")
            location = city_el.get_text(strip=True) if city_el else "Maroc"
            
            contract_el = item.select_one(".contrat, .contract-type, [class*='type']")
            contract = contract_el.get_text(strip=True) if contract_el else "N/A"
            
            desc_el = item.select_one(".description, p.post, .summary")
            description = desc_el.get_text(strip=True) if desc_el else ""

            return {
                'source': 'Rekrute',
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
            
            # Méthode 1: Recherche par classes classiques
            desc = soup.find('div', class_=['description', 'poste', 'mission'])
            profile = soup.find('div', class_=['profil', 'profile'])
            
            description_text = desc.get_text(separator='\n', strip=True) if desc else ''
            profile_text = profile.get_text(separator='\n', strip=True) if profile else ''

            # Méthode 2: Recherche par titres de sections (structure actuelle de Rekrute)
            if not description_text:
                poste_heading = soup.find(lambda e: e.name in ['h2', 'h3', 'h4'] and 'Poste' in e.text)
                if poste_heading and poste_heading.find_next_sibling():
                    description_text = poste_heading.find_next_sibling().get_text(separator='\n', strip=True)

            if not profile_text:
                profile_heading = soup.find(lambda e: e.name in ['h2', 'h3', 'h4'] and 'Profil' in e.text)
                if profile_heading and profile_heading.find_next_sibling():
                    profile_text = profile_heading.find_next_sibling().get_text(separator='\n', strip=True)

            full_description = (description_text + "\n\n" + profile_text).strip() if (description_text or profile_text) else ''
            
            return {
                'description': full_description or description_text,
                'profile': profile_text,
                'emails_found': extract_email_from_description(full_description)
            }
        except Exception as e:
            return {'description': '', 'profile': '', 'emails_found': []}