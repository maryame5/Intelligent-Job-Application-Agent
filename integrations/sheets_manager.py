# sheets_manager.py
import csv
import hashlib
import os
from datetime import datetime

class JobTracker:
    COLUMNS = [
        'Job Title', 'Company Name', 'Location', 'Job URL', 
        'Date Posted', 'Date Scraped', 'Source', 'Job Description',
        'Salary', 'Contract Type', 'Experience Required',
        'Hiring Manager Name', 'Hiring Manager Email', 'Hiring Manager LinkedIn',
        'Application Status', 'CV Tailored', 'Email Sent', 'Notes', 'Job ID',
        'Deterministic Score', 'LLM Score', 'Final ATS Score', 'Priority', 'Outcome'
    ]

    def __init__(self, filename='jobs_tracker.csv'):
        # Utiliser un chemin absolu par rapport au script pour le fichier CSV
        if not os.path.isabs(filename):
            script_dir = os.path.dirname(os.path.abspath(__file__))
            root_dir = os.path.dirname(script_dir)
            self.filename = os.path.join(root_dir, filename)
        else:
            self.filename = filename
            
        if not os.path.exists(self.filename):
            self._create_csv()
        else:
            self._migrate_existing_rows()
        print(f"[DOSSIER] Suivi des jobs activé localement dans : {self.filename}")

    def _create_csv(self):
        with open(self.filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(self.COLUMNS)

    def _generate_job_id(self, job):
        raw_value = '|'.join([
            str(job.get('job_url', '') or ''),
            str(job.get('job_title', '') or ''),
            str(job.get('company_name', '') or ''),
            str(job.get('source', '') or ''),
            str(job.get('date_scraped', '') or ''),
        ])
        digest = hashlib.sha1(raw_value.encode('utf-8')).hexdigest()[:10].upper()
        return f'JOB-{digest}'

    def ensure_job_id(self, job):
        if not job.get('job_id'):
            job['job_id'] = self._generate_job_id(job)
        return job['job_id']

    def _migrate_existing_rows(self):
        if not os.path.exists(self.filename):
            return

        with open(self.filename, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return

            missing_cols = [c for c in self.COLUMNS if c not in reader.fieldnames]
            if not missing_cols:
                return

            fieldnames = list(reader.fieldnames) + missing_cols
            rows = []
            for row in reader:
                if 'Job ID' in missing_cols and not row.get('Job ID'):
                    row['Job ID'] = self._generate_job_id(row)
                for col in missing_cols:
                    if col == 'Outcome':
                        row['Outcome'] = row.get('Outcome', 'pending')
                    else:
                        row[col] = row.get(col, '')
                rows.append(row)

        with open(self.filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def add_jobs(self, jobs):
        if not jobs:
            return
            
        # Lire les URLs existantes pour éviter les doublons
        existing_urls = set()
        if os.path.exists(self.filename):
            with open(self.filename, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    existing_urls.add(row.get('Job URL', ''))

        new_rows = []
        for job in jobs:
            self.ensure_job_id(job)
            url = job.get('job_url', '')
            if url and url in existing_urls:
                continue
                
            row = [
                job.get('job_title', ''),
                job.get('company_name', ''),
                job.get('location', ''),
                url,
                job.get('date_posted', ''),
                job.get('date_scraped', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                job.get('source', ''),
                job.get('description', '')[:5000].replace('\n', ' ').replace('\r', ''),
                job.get('salary', 'N/A'),
                job.get('contract_type', 'N/A'),
                job.get('experience_required', 'N/A'),
                '', '', '', # Manager info
                'New', 'No', 'No', '', job.get('job_id', ''), # Status
                job.get('deterministic_score', ''),
                job.get('llm_score', ''),
                job.get('final_ats_score', ''),
                job.get('priority', ''),
                job.get('outcome', 'pending')
            ]
            new_rows.append(row)
            if url:
                existing_urls.add(url)

        if new_rows:
            with open(self.filename, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerows(new_rows)
            print(f"✅ {len(new_rows)} nouveaux jobs ajoutés dans {self.filename}")
        else:
            print("ℹ️ Aucun nouveau job à ajouter (déjà présents ou liste vide).")

    def get_pending_jobs(self, limit=15, unscored_only=False):
        pending = []
        if not os.path.exists(self.filename):
            return pending
            
        with open(self.filename, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Si unscored_only=True, on ne prend que les jobs sans score
                if unscored_only:
                    has_score = bool((row.get('LLM Score') or '').strip() or (row.get('Deterministic Score') or '').strip())
                    if has_score:
                        continue

                status = row.get('Application Status', '')
                cv_done = row.get('CV Tailored', '')

                # Ignorer les jobs déjà traités, dont le CV est fait, ou marqués comme non éligibles
                if cv_done == 'Yes' or status in {'Rejected_Blacklist', 'Skipped_Short_Description', 'Applied'} or 'Documents Ready' in status:
                    continue

                if status == 'New' or cv_done == 'No':
                    pending.append(row)
                    if limit and len(pending) >= limit:
                        break
        return pending

    def update_job_status(
        self,
        job_url,
        status=None,
        cv_tailored=None,
        email_sent=None,
        description=None,
        notes=None,
        deterministic_score=None,
        llm_score=None,
        final_ats_score=None,
        priority=None,
        outcome=None
    ):
        if not os.path.exists(self.filename):
            return
        
        rows = []
        updated = False
        with open(self.filename, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames or self.COLUMNS)
            # Ensure missing fieldnames are added if needed
            for col in self.COLUMNS:
                if col not in fieldnames:
                    fieldnames.append(col)

            for row in reader:
                if row.get('Job URL') == job_url or (job_url and row.get('Job ID') == job_url):
                    if status is not None: row['Application Status'] = status
                    if cv_tailored is not None: row['CV Tailored'] = cv_tailored
                    if email_sent is not None: row['Email Sent'] = email_sent
                    if description is not None: row['Job Description'] = description[:5000].replace('\n', ' ').replace('\r', '')
                    if notes is not None: row['Notes'] = notes
                    if deterministic_score is not None: row['Deterministic Score'] = str(deterministic_score)
                    if llm_score is not None: row['LLM Score'] = str(llm_score)
                    if final_ats_score is not None: row['Final ATS Score'] = str(final_ats_score)
                    if priority is not None: row['Priority'] = str(priority)
                    if outcome is not None: row['Outcome'] = str(outcome)
                    updated = True
                rows.append(row)
        
        if updated:
            with open(self.filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

    def update_job_outcome(self, identifier: str, outcome: str) -> bool:
        """
        Met à jour la colonne Outcome (pending, no_response, rejected, interview, offer)
        en recherchant par Job ID, Job URL, ou sous-chaîne du nom de l'entreprise.
        """
        valid_outcomes = {"pending", "no_response", "rejected", "interview", "offer"}
        clean_outcome = outcome.strip().lower()
        if clean_outcome not in valid_outcomes:
            print(f"⚠️ Outcome invalide: '{outcome}'. Valeurs autorisées: {', '.join(sorted(valid_outcomes))}")
            return False

        if not os.path.exists(self.filename):
            print(f"⚠️ Fichier tracker introuvable: {self.filename}")
            return False

        rows = []
        updated_count = 0
        with open(self.filename, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames or self.COLUMNS)
            if 'Outcome' not in fieldnames:
                fieldnames.append('Outcome')

            ident_lower = identifier.strip().lower()
            for row in reader:
                row_id = (row.get('Job ID') or '').lower()
                row_url = (row.get('Job URL') or '').lower()
                row_company = (row.get('Company Name') or '').lower()

                if ident_lower in [row_id, row_url] or (len(ident_lower) >= 3 and ident_lower in row_company):
                    row['Outcome'] = clean_outcome
                    updated_count += 1
                    print(f"✅ Outcome mis à jour -> {clean_outcome} pour [{row.get('Job ID')}] {row.get('Job Title')} @ {row.get('Company Name')}")
                rows.append(row)

        if updated_count > 0:
            with open(self.filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            return True
        else:
            print(f"⚠️ Aucun job correspondant trouvé pour '{identifier}'.")
            return False

    def list_jobs(self):
        """Affiche les offres suivies avec leur ID, Titre, Entreprise, Priorité et Outcome."""
        if not os.path.exists(self.filename):
            print(f"⚠️ Fichier tracker introuvable: {self.filename}")
            return

        with open(self.filename, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if not rows:
            print("ℹ️ Aucun job dans le tracker.")
            return

        print("\n" + "═" * 85)
        print(f"{'JOB ID':<14} | {'ENTREPRISE':<20} | {'POSTE':<25} | {'PRIO':<4} | {'OUTCOME':<12}")
        print("─" * 85)
        for r in rows:
            job_id = r.get('Job ID', 'N/A')
            comp = (r.get('Company Name') or 'N/A')[:20]
            title = (r.get('Job Title') or 'N/A')[:25]
            prio = r.get('Priority', '-') or '-'
            outcome = r.get('Outcome', 'pending') or 'pending'
            print(f"{job_id:<14} | {comp:<20} | {title:<25} | {prio:<4} | {outcome:<12}")
        print("═" * 85 + "\n")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="Gestionnaire du Tracker de Candidatures")
    parser.add_argument('--list', action='store_true', help="Lister les candidatures et leur statut Outcome")
    parser.add_argument('--update', nargs=2, metavar=('IDENTIFIER', 'OUTCOME'), help="Mettre à jour l'Outcome d'un job (ex: JOB-ABC123 interview)")
    args = parser.parse_args()

    tracker = JobTracker()
    if args.list:
        tracker.list_jobs()
    elif args.update:
        tracker.update_job_outcome(args.update[0], args.update[1])
    else:
        parser.print_help()