# scraper_linkedin.py
import requests
from bs4 import BeautifulSoup
import json
import time
import re

def extract_email_from_description(text):
    if not text: return []
    emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
    blacklist = ['noreply', 'support', 'contact', 'info']
    return [e for e in emails if not any(b in e.lower() for b in blacklist)]

class LinkedInScraper:
    def __init__(self):
        self.session = requests.Session()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8',
        }

    def search_jobs(self, keywords, location="Morocco", pages=3):
        jobs = []
        for page in range(pages):
            start = page * 25
            url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
            params = {
                'keywords': keywords,
                'location': location,
                'start': start,
                'f_TPR': 'r604800'  # Derniere semaine
            }
            try:
                resp = self.session.get(url, headers=self.headers, params=params, timeout=30)
                if resp.status_code != 200:
                    print(f"Page {page}: Status {resp.status_code}")
                    continue
                soup = BeautifulSoup(resp.text, 'html.parser')
                job_cards = soup.find_all('div', class_='base-search-card')
                for card in job_cards:
                    job = self._parse_card(card)
                    if job:
                        jobs.append(job)
                time.sleep(2)
            except Exception as e:
                print(f"Error page {page}: {e}")
                continue
        return jobs

    def _parse_card(self, card):
        try:
            title = card.find('h3', class_='base-search-card__title')
            company = card.find('h4', class_='base-search-card__subtitle')
            location = card.find('span', class_='job-search-card__location')
            link = card.find('a', class_='base-card__full-link')
            job_url = link['href'] if link else None
            job_id = None
            # 1. Vérifier dans data-entity-urn (ex: urn:li:jobPosting:4454974477)
            urn = card.get('data-entity-urn') or ''
            if 'urn:li:jobPosting:' in urn:
                job_id = urn.split('urn:li:jobPosting:')[-1].strip()
            # 2. Fallback regex sur l'URL
            if not job_id and job_url:
                match = re.search(r'([0-9]{8,12})', job_url)
                job_id = match.group(1) if match else None
            return {
                'source': 'LinkedIn',
                'job_title': title.text.strip() if title else 'N/A',
                'company_name': company.text.strip() if company else 'N/A',
                'location': location.text.strip() if location else 'N/A',
                'job_url': job_url,
                'job_id': job_id,
                'date_scraped': time.strftime('%Y-%m-%d %H:%M:%S'),
                'status': 'New'
            }
        except Exception as e:
            return None

    def get_job_details(self, job_id):
        if not job_id:
            return {'description': '', 'seniority': 'N/A', 'employment_type': 'N/A', 'emails_found': []}
        url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }
        try:
            resp = self.session.get(url, headers=headers, timeout=30)
            if resp.status_code != 200:
                return {'description': '', 'seniority': 'N/A', 'employment_type': 'N/A', 'emails_found': []}
            soup = BeautifulSoup(resp.text, 'html.parser')
            description_el = (
                soup.find('div', class_='description__text') 
                or soup.find('div', class_='show-more-less-html__markup')
                or soup.find('section', class_='description')
            )
            criteria = soup.find_all('li', class_='job-criteria__item')
            description_text = description_el.get_text(separator='\n', strip=True) if description_el else ''
            return {
                'description': description_text,
                'seniority': criteria[0].text.strip() if len(criteria) > 0 else 'N/A',
                'employment_type': criteria[1].text.strip() if len(criteria) > 1 else 'N/A',
                'emails_found': extract_email_from_description(description_text)
            }
        except Exception as e:
            return {'description': '', 'seniority': 'N/A', 'employment_type': 'N/A', 'emails_found': []}