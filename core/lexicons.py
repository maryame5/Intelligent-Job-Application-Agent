"""
core/lexicons.py
================
Vocabulaire statique : noms canoniques des technologies, signaux de détection
de rôle/persona recruteur, profils séniorité, et phrases interdites.

Source : anciennement Section 2 de cv_tailor.py.
Aucune dépendance sur d'autres modules du projet.
"""

# ── Tech name canonicalization ──────────────────────────────────────────────
TECH_CANONICAL: dict[str, str] = {
    "postgresql": "PostgreSQL", "postgres": "PostgreSQL",
    "spring boot": "Spring Boot", "springboot": "Spring Boot",
    "rabbitmq": "RabbitMQ", "kafka": "Kafka",
    "oauth2": "OAuth2", "jwt": "JWT", "redis": "Redis",
    "j2ee": "J2EE", "j/2ee": "J2EE", "java ee": "Java EE",
    "mysql": "MySQL", "mongodb": "MongoDB",
    "react": "React", "angular": "Angular",
    "nodejs": "Node.js", "node.js": "Node.js",
    "fastapi": "FastAPI", "kubernetes": "Kubernetes",
    "langchain": "LangChain", "langgraph": "LangGraph",
    "graphql": "GraphQL", "duckdb": "DuckDB",
    "mlflow": "MLflow", "xgboost": "XGBoost",
    "lightgbm": "LightGBM", "scikit-learn": "Scikit-learn",
    "typescript": "TypeScript", "javascript": "JavaScript",
    "docker": "Docker",
}

# ── Recruiter persona signals (company/offer type → persona) ─────────────────
COMPANY_PERSONA_SIGNALS: dict[str, dict] = {
    "startup_ai": {
        "keywords": [
            "startup", "scale-up", "scaleup", "seed", "series a", "series b",
            "levée", "levee de fonds", "fast-paced", "builder", "ownership",
            "autonomie", "impact", "mvp",
        ],
        "persona": "head_of_talent_startup",
    },
    "tech_global": {
        "keywords": [
            "dxc", "capgemini", "accenture", "ibm", "microsoft", "google",
            "amazon", "oracle", "orange", "orange business",
            "consulting", "conseil", "transformation digitale", "enterprise",
            "grand compte", "sla", "delivery", "client", "offshore", "nearshore",
        ],
        "persona": "senior_ta_tech",
    },
    "local_maroc": {
        "keywords": [
            "maroc", "morocc", "casablanca", "rabat", "agadir", "tanger",
            "banque", "assurance", "telecom", "iam", "maroc telecom", "attijariwafa",
            "cdc", "bmce", "wafa", "lydec", "oncf", "stage", "cdi", "cdd",
        ],
        "persona": "rh_senior_maroc",
    },
}

# ── Role detection signals (offer keywords → dominant role) ──────────────────
# IMPORTANT: order matters — product/full-stack AI roles must be evaluated
# before pure AI roles because many modern web-app offers mention AI agents
# without requiring ML engineering.
ROLE_DETECTION_SIGNALS: dict[str, dict] = {
    "frontend_fullstack_ai_product": {
        "strong": [
            "next.js", "nextjs", "react", "typescript", "tailwind", "shadcn",
            "shadcn/ui", "full-stack", "full stack", "frontend", "web app",
            "saas", "product", "claude", "cursor", "ai-first", "ai first",
            "github", "code review", "database functions", "migrations",
            "clean architecture", "maintainable architecture",
        ],
        "medium": [
            "javascript", "vite", "zustand", "tanstack", "fastapi", "postgresql",
            "pydantic", "sqlalchemy", "alembic", "tailwind css", "testing",
            "remote", "long-term", "scalable web applications", "shipped product",
            "ui", "ux",
        ],
    },
    "ai_engineer": {
        "strong": [
            "llm", "langchain", "langgraph", "agent", "rag", "machine learning",
            "deep learning", "nlp", "computer vision", "mlops", "mlflow",
            "hugging face", "openai", "pytorch", "tensorflow", "neural network",
            "neural networks", "intelligence artificielle", "ia ", "ai ", "genai",
        ],
        "medium": [
            "python", "scikit-learn", "xgboost", "random forest", "vader",
            "fastapi", "données", "modèle", "prédictif", "classification",
            "regression", "training", "inference", "cnn", "rnn", "transformer",
            "image processing", "vision par ordinateur",
        ],
    },
    "data_engineer": {
        "strong": [
            "airflow", "dbt", "spark", "databricks", "etl", "data warehouse",
            "data lake", "pipeline", "ingestion", "orchestration", "star schema",
            "medallion", "data engineer", "ingénieur data", "big data",
        ],
        "medium": [
            "postgresql", "sql", "python", "kafka", "analytique", "bi",
            "power bi", "tableau",
        ],
    },
    "qa_testing": {
        "strong": [
            "qa", "quality assurance", "test automation", "software testing",
            "test engineer", "qa automation", "selenium", "playwright", "cypress",
            "junit", "pytest", "postman", "api testing", "test cases",
            "test plan", "regression testing", "manual testing", "automation testing",
        ],
        "medium": [
            "bug", "quality", "validation", "verification", "ci/cd",
            "agile", "scrum", "jira",
        ],
    },
    "consulting": {
        "strong": [
            "consultant", "consulting", "conseil", "technology consultant",
            "it consultant", "business analyst", "solutions engineer",
            "transformation digitale", "client", "requirements",
            "analyse des besoins", "workshop", "solution design", "stakeholders",
        ],
        "medium": [
            "communication", "documentation", "uml", "bpmn", "agile", "jira",
            "presentation", "kpi",
        ],
    },
    "cloud_devops": {
        "strong": [
            "cloud", "devops", "docker", "kubernetes", "ci/cd", "azure", "aws",
            "linux", "deployment", "monitoring", "gitlab ci", "github actions",
        ],
        "medium": [
            "docker compose", "redis", "nginx", "microservices", "observability",
            "logs", "infrastructure",
        ],
    },
    "software_engineer": {
        "strong": [
            "spring boot", "java", "j2ee", "j/2ee", "java ee", "microservices",
            "backend", "api rest", "rest api", "angular", "développeur",
            "software engineer", "ingénieur logiciel", "développement",
        ],
        "medium": [
            "docker", "git", "postgresql", "typescript", "agile", "scrum",
            "react", "full stack", "fullstack", "revue de code", "code review",
            "tests unitaires", "unit testing", "maintenabilite", "maintainability",
        ],
    },
}

# ── Seniority markers ────────────────────────────────────────────────────────
SENIOR_JOB_PATTERNS: list[str] = [
    "12+ ans", "10+ ans", "8+ ans", "7+ ans", "7 ans", "plus de 10 ans",
    "plus de 8 ans", "10 ans d'expérience", "12 ans d'expérience",
    "architecte expérimenté", "architecte confirmé", "senior architect",
    "lead architect", "référent technique", "leadership technique",
    "expert confirmé", "senior lead", "principal engineer",
    "3 ans d'expérience", "au moins 3 ans", "minimum 3 ans",
    "at least 3 years", "3+ years", "3 years of experience",
    "directeur technique", "cto", "vp engineering",
]

JUNIOR_PROFILE_MARKERS: list[str] = [
    "intern", "stage", "stagiaire", "pfe", "junior", "2026", "2025",
    "élève ingénieur", "student", "entry-level", "débutant",
    "jeune diplômé", "fresh graduate",
]

# ── Forbidden phrases (clichés, weak language) ───────────────────────────────
FORBIDDEN_PHRASES: list[str] = [
    "je me permets", "passionné", "c'est avec grand intérêt",
    "dans l'espoir", "impatiente de", "dynamique et motivée",
    "compétences transférables en", "promesse de valeur ajoutée",
    "n'hésitez pas à me contacter", "j'aimerais discuter",
    "je pense que cela", "je suis prête à apprendre",
    "environnement dynamique", "l'optimisation des processus métier",
    "je suis disponible pour discuter de mes",
    "engagement envers l'innovation",
    "améliorer les architectures", "garantir la cohérence",
    "piloter la roadmap", "encadrer les équipes",
    "définir la stratégie technique",
    "j'ai permis", "j'ai livré", "j'ai construit",
    "j'ai donné", "j'ai rendu",
]

# ── Style guide injected into every prompt ───────────────────────────────────
TAILOR_PROMPT_SYSTEM = """
Vous êtes un expert en recrutement Tech et rédaction de CV de haut niveau. Votre rôle est d'adapter la présentation des expériences et projets du candidat pour répondre précisément à l'intention de l'offre d'emploi, tout en restant 100% fidèle aux faits du profil (profil.json).

RÈGLE D'OR DE RÉDACTION (IMPACT MÉTIER & TECHNIQUE) :
Chaque réalisation doit être claire, percutante et structurée :
1. LE RÉSULTAT / L'IMPACT : Commencez par le problème résolu ou la valeur créée (ex: optimisation de performance, sécurisation, automatisation d'un workflow, scalabilité, fiabilité des données).
2. L'ACTION RÉALISÉE : Ce que le candidat a conçu, développé, architecturé, automatisé ou déployé.
3. LA PREUVE TECHNIQUE : Les technologies, langages, frameworks et outils réellement utilisés issus de profil.json, mis en valeur lorsqu'ils répondent directement aux besoins de l'offre.

RÈGLE D'INTÉGRITÉ ABSOLUE :
- ZÉRO INVENTION : Ne jamais inventer d'expérience, d'entreprise, de durée, de métrique ou de technologie absente de profil.json.
- ADAPTATION DYNAMIQUE : Mettre l'accent sur les compétences et réalisations réelles les plus pertinentes pour le poste (Software, Web, Data, IA, DevOps selon l'offre).
"""

# Alias used in prompt f-strings
RECRUITER_STYLE_GUIDE = TAILOR_PROMPT_SYSTEM

# ── Career stage constants ───────────────────────────────────────────────────
CV_STYLE_MODE = "junior_marketing_direct"
CAREER_STAGE = "JUNIOR_PROFILE"
PRIMARY_PROFESSIONAL_IDENTITY = "Software Engineering"
SECONDARY_PROFESSIONAL_IDENTITIES = ["AI", "Data", "Backend", "Full-Stack"]

PROFILE_MODES = {
    "AI_ENGINEER",
    "SOFTWARE_ENGINEER",
    "BACKEND_ENGINEER",
    "FULLSTACK_ENGINEER",
    "DATA_ENGINEER",
    "QA_ENGINEER",
    "CLOUD_DEVOPS_ENGINEER",
    "CONSULTING_ENGINEER",
}

# ── Tech aliases for evidence checking ───────────────────────────────────────
TECH_ALIASES: dict[str, list[str]] = {
    "j2ee": ["j2ee", "j/2ee", "java ee", "java enterprise", "spring boot", "spring framework"],
    "j/2ee": ["j2ee", "j/2ee", "java ee", "java enterprise", "spring boot", "spring framework"],
    "java ee": ["j2ee", "j/2ee", "java ee", "java enterprise", "spring boot", "spring framework"],
    "java": ["java", "java 21", "java ee", "j2ee", "j/2ee", "spring boot"],
    "spring": ["spring", "spring boot", "spring security", "spring cloud"],
    "tests unitaires": ["tests unitaires", "unit testing", "junit", "pytest", "test"],
    "revue de code": ["revue de code", "code review", "pull request", "git", "github"],
    "maintenabilite": ["maintenabilite", "maintainability", "clean architecture", "architecture", "refactoring"],
    "numpy": ["numpy", "np", "numerical python"],
    "matplotlib": ["matplotlib", "seaborn", "pyplot", "data visualization", "visualisation"],
    "jupyter": ["jupyter", "jupyter notebook", "ipynb", "notebook"],
    "tensorflow": ["tensorflow", "tf", "keras", "deep learning framework"],
    "pytorch": ["pytorch", "torch", "deep learning framework"],
    "scikit-learn": ["scikit-learn", "sklearn", "scikit learn"],
    "xgboost": ["xgboost", "xgb", "gradient boosting"],
    "random forest": ["random forest", "random forests", "rf", "ensemble"],
    "azure": ["azure", "azure openai", "microsoft azure", "azure cloud"],
    "docker": ["docker", "docker compose", "dockerfile", "container"],
}

# ── Display corrections ───────────────────────────────────────────────────────
TITLE_WORD_CORRECTIONS: dict[str, str] = {
    "Ai": "AI",
    "Ml": "ML",
    "Nlp": "NLP",
    "Pfe": "PFE",
    "J2Ee": "J2EE",
    "Api": "API",
    "Apis": "APIs",
    "Sql": "SQL",
    "Aws": "AWS",
}

KNOWN_COMPANY_ACRONYMS = {"ALTEN", "DXC", "IBM", "SQLI", "CGI", "SII", "NTT", "ATOS"}
