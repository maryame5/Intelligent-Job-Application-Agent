# email_sender.py
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import base64
import os

class EmailOutreach:
    SCOPES = ['https://www.googleapis.com/auth/gmail.send']

    def __init__(self, credentials_file='gmail_credentials.json'):
        if not os.path.exists(credentials_file):
            raise FileNotFoundError(
                f"Credentials Gmail introuvables: {credentials_file}. "
                "Ajoutez ce fichier ou laissez JOB_AGENT_SEND_EMAILS=false."
            )
        self.creds = Credentials.from_authorized_user_file(credentials_file, self.SCOPES)
        self.service = build('gmail', 'v1', credentials=self.creds)

    def send_application_email(self, to_email, job_title, company_name, 
                                cover_letter, resume_markdown, 
                                hiring_manager_name="", candidate_profile=None):
        candidate_profile = candidate_profile or {}
        identity = candidate_profile.get("identity", candidate_profile)
        full_name = identity.get("full_name", "")
        phone = identity.get("phone", "")
        links = identity.get("links", {})
        linkedin = links.get("linkedin") or identity.get("linkedin", "")

        greeting = f"Bonjour {hiring_manager_name}," if hiring_manager_name else "Bonjour,"
        subject = f"Candidature - {job_title} - {company_name}"
        body = (
            greeting + "\n\n" +
            cover_letter + "\n\n" +
            "---\n\n" +
            "Vous trouverez ci-joint mon CV personnalise pour cette opportunite chez " + company_name + ".\n\n" +
            "Je reste a votre entiere disposition pour un entretien.\n\n" +
            "Cordialement,\n"
            f"{full_name}\n"
            f"{phone}\n"
            f"{linkedin}\n"
        )
        message = MIMEMultipart()
        message['to'] = to_email
        message['subject'] = subject
        message.attach(MIMEText(body, 'plain', 'utf-8'))

        attachment = MIMEBase("text", "markdown")
        attachment.set_payload(resume_markdown.encode("utf-8"))
        encoders.encode_base64(attachment)
        safe_company = "".join(c if c.isalnum() else "_" for c in company_name).strip("_")
        attachment.add_header(
            "Content-Disposition",
            "attachment",
            filename=f"CV_{safe_company or 'candidature'}.md",
        )
        message.attach(attachment)

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        try:
            sent = self.service.users().messages().send(
                userId='me',
                body={'raw': raw}
            ).execute()
            print(f"Email sent! ID: {sent['id']}")
            return True
        except Exception as e:
            print(f"Error sending email: {e}")
            return False

    def send_follow_up(self, to_email, job_title, company_name, days_since=7):
        subject = f"Relance - Candidature {job_title} - {company_name}"
        body = (
            "Bonjour,\n\n"
            "Je me permets de relancer ma candidature pour le poste de " + job_title + " chez " + company_name + ",\n"
            "deposee il y a " + str(days_since) + " jours.\n\n"
            "Je reste tres interesse(e) par cette opportunite et je serais ravi(e) d'echanger avec vous.\n\n"
            "Cordialement,\n"
            "[Ton Nom]\n"
        )
        message = MIMEText(body, 'plain', 'utf-8')
        message['to'] = to_email
        message['subject'] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        try:
            sent = self.service.users().messages().send(userId='me', body={'raw': raw}).execute()
            return True
        except Exception as e:
            print(f"Error: {e}")
            return False
