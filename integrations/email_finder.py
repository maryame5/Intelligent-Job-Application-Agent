import requests
from bs4 import BeautifulSoup
import re
import time
import json
from urllib.parse import urljoin, urlparse

class EmailFinder:
    """
    Trouve les emails de recruteurs/hiring managers pour une entreprise donnee
    Methodes gratuites uniquement
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.found_emails = set()

    # ============================================================
    # METHODE 1: Scraper le site web de l'entreprise
    # ============================================================
    def find_from_website(self, company_name, domain=None):
        """
        Scrape le site web de l'entreprise pour trouver des emails
        """
        if not domain:
            domain = self._guess_domain(company_name)

        emails = []
        pages_to_check = [
            f"https://{domain}/contact",
            f"https://{domain}/contactez-nous",
            f"https://{domain}/equipe",
            f"https://{domain}/team",
            f"https://{domain}/carriere",
            f"https://{domain}/carrieres",
            f"https://{domain}/a-propos",
            f"https://{domain}/about",
            f"https://{domain}/",
        ]

        for page_url in pages_to_check:
            try:
                resp = self.session.get(page_url, timeout=15)
                if resp.status_code == 200:
                    page_emails = self._extract_emails(resp.text)
                    emails.extend(page_emails)

                    soup = BeautifulSoup(resp.text, 'html.parser')
                    for link in soup.find_all('a', href=True):
                        href = link['href'].lower()
                        if any(kw in href for kw in ['contact', 'carriere', 'recrutement', 'join', 'team']):
                            full_url = urljoin(page_url, link['href'])
                            try:
                                sub_resp = self.session.get(full_url, timeout=10)
                                if sub_resp.status_code == 200:
                                    sub_emails = self._extract_emails(sub_resp.text)
                                    emails.extend(sub_emails)
                            except:
                                pass
                            time.sleep(0.5)

                    time.sleep(1)
            except Exception as e:
                continue

        valid_emails = self._filter_valid_emails(list(set(emails)))
        return valid_emails

    # ============================================================
    # METHODE 2: Patterns d'emails marocains
    # ============================================================
    def generate_email_permutations(self, first_name, last_name, domain):
        """
        Genere toutes les combinaisons possibles d'emails
        basees sur les patterns typiques des entreprises marocaines
        """
        first = first_name.lower().strip()
        last = last_name.lower().strip()
        first_initial = first[0] if first else ''
        last_initial = last[0] if last else ''

        patterns = [
            f"{first}.{last}@{domain}",
            f"{first}_{last}@{domain}",
            f"{first}-{last}@{domain}",
            f"{first}{last}@{domain}",
            f"{first_initial}.{last}@{domain}",
            f"{first_initial}{last}@{domain}",
            f"{first}@{domain}",
            f"{last}@{domain}",
            f"{first_initial}@{domain}",
            f"{first}.{last_initial}@{domain}",
            f"{first}{last_initial}@{domain}",
            f"{last}.{first}@{domain}",
            f"{last}_{first}@{domain}",
            f"{first}-{last}@{domain}",
        ]

        generic = [
            f"contact@{domain}",
            f"recrutement@{domain}",
            f"rh@{domain}",
            f"hr@{domain}",
            f"jobs@{domain}",
            f"careers@{domain}",
            f"info@{domain}",
            f"direction@{domain}",
        ]

        return list(set(patterns + generic))

    # ============================================================
    # METHODE 3: Google Dorks
    # ============================================================
    def google_dork_search(self, company_name, domain=None):
        """
        Utilise Google Custom Search API (gratuit: 100 req/jour)
        """
        queries = [
            f'site:{domain} "@" "email" "contact"' if domain else f'"{company_name}" "@" "email" "Maroc"',
            f'site:{domain} "recrutement" OR "carrieres" OR "join us"' if domain else f'"{company_name}" "recrutement" "email"',
            f'"{company_name}" "Maroc" "contact" "@"',
        ]
        return queries

    # ============================================================
    # METHODE 4: LinkedIn Profile Scraper (Guest)
    # ============================================================
    def find_hiring_manager_linkedin(self, company_name, job_title_keywords):
        """
        Cherche le hiring manager sur LinkedIn (version guest, sans login)
        Retourne les queries de recherche a executer
        """
        search_queries = []

        for keyword in job_title_keywords:
            search_queries.append(f'"{company_name}" "{keyword}" site:linkedin.com/in/')

        rh_titles = [
            "Talent Acquisition", "Recruteur", "HR Manager",
            "Responsable RH", "Charge de Recrutement",
            "Human Resources", "People Operations"
        ]
        for title in rh_titles:
            search_queries.append(f'"{company_name}" "{title}" site:linkedin.com/in/')

        return search_queries

    # ============================================================
    # METHODE 5: Chercher dans l'offre d'emploi
    # ============================================================
    def extract_email_from_job_posting(self, job_description, job_url=None):
        """
        Extrait les emails directement de la description de l'offre
        """
        emails = self._extract_emails(job_description)

        contact_patterns = [
            r'contact(?:ez)?\s+(?:\w+\s+)?[aà]\s*[:\s]*([^\s@]+@[^\s@]+\.[^\s@]+)',
            r'envoyez\s+(?:votre\s+)?(?:cv|curriculum|candidature)\s+[aà]\s*[:\s]*([^\s@]+@[^\s@]+\.[^\s@]+)',
            r'postuler\s+[aà]\s*[:\s]*([^\s@]+@[^\s@]+\.[^\s@]+)',
            r'e-?mail\s*[:\s]*([^\s@]+@[^\s@]+\.[^\s@]+)',
            r'adresse\s+e-?mail\s*[:\s]*([^\s@]+@[^\s@]+\.[^\s@]+)',
        ]

        for pattern in contact_patterns:
            matches = re.findall(pattern, job_description, re.IGNORECASE)
            emails.extend(matches)

        return self._filter_valid_emails(list(set(emails)))

    # ============================================================
    # UTILITAIRES
    # ============================================================
    def _extract_emails(self, text):
        """Extrait tous les emails d'un texte"""
        if not text:
            return []
        pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        return re.findall(pattern, text)

    def _filter_valid_emails(self, emails):
        """Filtre les emails valides et pertinents"""
        filtered = []
        blacklist = [
            'example.com', 'test.com', 'domain.com', 'email.com',
            'gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com',
            'noreply', 'no-reply', 'donotreply', 'support',
            'admin@', 'webmaster@', 'postmaster@', 'hostmaster@'
        ]

        for email in emails:
            email = email.lower().strip()
            if any(b in email for b in blacklist):
                continue
            if re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
                filtered.append(email)

        return list(set(filtered))

    def _guess_domain(self, company_name):
        """Devine le domaine a partir du nom de l'entreprise"""
        if not company_name:
            return 'example.ma'
        clean = company_name.lower().replace(' ', '').replace('-', '').replace('&', '')
        extensions = ['.ma', '.com', '.net', '.org']
        candidates = [
            clean,
            clean + 'group',
            clean.replace('groupe', ''),
            clean + 'maroc',
        ]

        for ext in extensions:
            for cand in candidates:
                domain = cand + ext
                try:
                    resp = self.session.head(f'https://{domain}', timeout=3, allow_redirects=True)
                    if resp.status_code < 400:
                        return domain
                except:
                    pass

        return clean + '.ma'

    # ============================================================
    # METHODE COMPLETE: Pipeline pour une offre
    # ============================================================
    def find_contact_for_job(self, job):
        """
        Pipeline complet pour trouver le contact d'une offre
        """
        results = {
            'company_name': job.get('company_name'),
            'job_title': job.get('job_title'),
            'emails_found': [],
            'hiring_manager_name': None,
            'hiring_manager_title': None,
            'linkedin_search_queries': [],
            'domain': None,
            'application_method': None,
            'confidence': 'low'
        }

        company = job.get('company_name', '')

        # Etape 1: Chercher dans la description de l'offre
        desc_emails = self.extract_email_from_job_posting(job.get('description', ''))
        if desc_emails:
            results['emails_found'].extend(desc_emails)
            results['application_method'] = 'email_direct_from_job_posting'
            results['confidence'] = 'high'

        # Etape 2: Deviner le domaine et scraper le site
        domain = self._guess_domain(company)
        results['domain'] = domain

        if not desc_emails:
            web_emails = self.find_from_website(company, domain)
            if web_emails:
                results['emails_found'].extend(web_emails)
                results['application_method'] = 'email_from_company_website'
                results['confidence'] = 'medium'

        # Etape 3: Generer les queries LinkedIn
        job_keywords = job.get('job_title', '').split()[:3]
        results['linkedin_search_queries'] = self.find_hiring_manager_linkedin(company, job_keywords)

        # Etape 4: Si toujours pas d'email, proposer les generiques
        if not results['emails_found']:
            generic_emails = [
                f"recrutement@{domain}",
                f"rh@{domain}",
                f"contact@{domain}",
                f"careers@{domain}",
                f"jobs@{domain}",
            ]
            results['emails_found'] = generic_emails
            results['application_method'] = 'generic_email_guess'
            results['confidence'] = 'low'

        results['emails_found'] = list(set(results['emails_found']))
        return results

if __name__ == '__main__':
    finder = EmailFinder()

    job = {
        'company_name': 'Capgemini Maroc',
        'job_title': 'Developpeur Python Senior',
        'job_url': 'https://example.com/job/123',
        'description': 'Nous recrutons un developpeur Python. Envoyez votre CV a recrutement@capgemini.com'
    }

    result = finder.find_contact_for_job(job)
    print(json.dumps(result, indent=2, ensure_ascii=False))
