import json
import re
import os
import logging
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator
from mistralai import Mistral

# ─── Logging ────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger(__name__)

# ─── App ────────────────────────────────────────────────────────
app = FastAPI(
    title="Calistheni API",
    description="Agent IA Calisthenics — génération de programmes personnalisés",
    version="1.0.0",
)

# ─── CORS ───────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://calistheni.com",
        "https://www.calistheni.com",
        "http://localhost",
        "http://localhost:3000",
        "http://127.0.0.1:5500",  # Live Server VS Code
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Mistral client ─────────────────────────────────────────────
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY")
if not MISTRAL_API_KEY:
    raise RuntimeError("MISTRAL_API_KEY manquante dans les variables d'environnement")

mistral = Mistral(api_key=MISTRAL_API_KEY)
MODEL = os.environ.get("MISTRAL_MODEL", "mistral-small-latest")

# ─── Schémas Pydantic ───────────────────────────────────────────
SKILLS_VALIDES = {
    "Front Lever", "Back Lever", "Planche", "Human Flag",
    "Muscle-Up", "Handstand", "Dragon Flag", "One Arm Pull-Up",
}

class FormData(BaseModel):
    skill_cible: str
    prerequis: dict = {}
    frequence_semaine: int
    duree_seance_min: int
    materiel: list[str]


# ─── Builder de prompt ───────────────────────────────────────────
LABELS_PREREQ = {"oui": "maîtrisé ✓", "en_cours": "en progression →", "non": "pas encore ✗"}

CONSEILS_PAR_SKILL = {
    "Front Lever": "Insiste sur la rétraction et dépression scapulaire. Progresse tuck → advanced tuck → one leg → straddle → full.",
    "Back Lever": "Commence toujours par skin the cat pour la mobilité. Priorité : tenir chaque progression 10 sec avant d'avancer.",
    "Planche": "La progression est lente (6–18 mois). Pseudo planche push-ups et lean quotidiens. Protège les poignets.",
    "Human Flag": "Travail bilatéral indispensable. Alterne côté fort/faible. Push-pull isométrique contre la barre.",
    "Muscle-Up": "L'explosivité et le false grip sont les deux clés. Ne saute pas l'étape du kipping pour apprendre la mécanique.",
    "Handstand": "Travail mur d'abord (dos), puis chest-to-wall, puis free. Travail de poignets quotidien obligatoire.",
    "Dragon Flag": "Hollow body est le fondement absolu. Progresser : tuck → single leg → straddle → full.",
    "One Arm Pull-Up": "Archer pull-ups et tractions lestées (+20–30kg) avant tout. Progression très lente, 6–12 mois minimum.",
}


def build_prompt(data: FormData) -> str:
    # Formatage prérequis
    if data.prerequis:
        prereq_lines = "\n".join(
            f"  - {k}: {LABELS_PREREQ.get(v, v)}"
            for k, v in data.prerequis.items()
        )
    else:
        prereq_lines = "  (non renseignés — suppose un niveau débutant intermédiaire)"

    # Conseils spécifiques au skill
    conseil_skill = CONSEILS_PAR_SKILL.get(data.skill_cible, "")

    # Calcul volume indicatif
    volume_note = (
        "Programme léger" if data.frequence_semaine <= 2
        else "Volume modéré" if data.frequence_semaine <= 4
        else "Volume élevé — prévoir récupération active"
    )

    return f"""Tu es Tarik, coach calisthenics expert avec 10 ans d'expérience.
Tu dois générer un programme de progression ultra-personnalisé pour un athlète.

═══ PROFIL ATHLÈTE ═══
Skill cible        : {data.skill_cible}
Fréquence          : {data.frequence_semaine} séances/semaine ({volume_note})
Durée par séance   : {data.duree_seance_min} minutes
Matériel disponible: {', '.join(data.materiel)}

═══ ÉVALUATION PRÉREQUIS ═══
{prereq_lines}

═══ DIRECTIVES COACH ═══
{conseil_skill}

═══ RÈGLES DU PROGRAMME ═══
1. Génère exactement 2 semaines de progression (semaine 1 et semaine 2 seulement)
2. Chaque semaine a exactement {data.frequence_semaine} séances
3. Adapte les exercices STRICTEMENT au matériel disponible
4. Respecte le volume cohérent avec {data.duree_seance_min} min/séance
5. La progression doit être réaliste semaine par semaine (volume ou intensité +5-10%)
6. Chaque conseil doit être CONCRET et TECHNIQUE (pas générique)
7. Utilise "duree_sec" pour les isométriques/holds, "reps" pour le dynamique (l'autre vaut null)
8. Les jours de repos : nomme-les "Repos actif" ou répartis intelligemment

═══ FORMAT DE RÉPONSE ═══
Réponds UNIQUEMENT avec le JSON ci-dessous, rien d'autre, aucun texte avant ou après.

```json
{{
  "skill_target": "{data.skill_cible}",
  "niveau_actuel": "description précise du niveau actuel basée sur les prérequis évalués",
  "duree_programme_semaines": 4,
  "programme": [
    {{
      "semaine": 1,
      "objectif": "Objectif spécifique et mesurable de cette semaine",
      "charge": "légère | modérée | élevée",
      "seances": [
        {{
          "jour": "Lundi",
          "focus": "Thème de la séance (ex: Force scapulaire, Technique tuck FL...)",
          "duree_estimee_min": {data.duree_seance_min},
          "exercices": [
            {{
              "id": "snake_case_id",
              "nom": "Nom complet de l'exercice",
              "sets": 3,
              "reps": 8,
              "duree_sec": null,
              "repos_sec": 90,
              "conseil": "Conseil technique précis et actionnable en une phrase",
              "media_key": "cle_pour_animation"
            }}
          ]
        }}
      ]
    }}
  ]
}}
```"""


# ─── Parsing JSON robuste ────────────────────────────────────────
def extract_json(raw: str) -> dict:
    """Extrait et parse le JSON même si le modèle ajoute du texte autour."""
    # 1. Cherche un bloc ```json ... ```
    match = re.search(r"```json\s*([\s\S]*?)```", raw)
    if match:
        return json.loads(match.group(1).strip())

    # 2. Cherche un bloc ``` ... ```
    match = re.search(r"```\s*([\s\S]*?)```", raw)
    if match:
        return json.loads(match.group(1).strip())

    # 3. Cherche le premier { ... } complet
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        return json.loads(match.group(0))

    raise ValueError("Aucun JSON valide trouvé dans la réponse du modèle")


def validate_programme(data: dict) -> dict:
    """Validation minimale de la structure retournée."""
    required_keys = {"skill_target", "niveau_actuel", "programme"}
    for k in required_keys:
        if k not in data:
            raise ValueError(f"Champ manquant dans la réponse IA : '{k}'")

    if not isinstance(data["programme"], list) or len(data["programme"]) == 0:
        raise ValueError("Le champ 'programme' doit être une liste non vide")

    return data


# ─── Routes ─────────────────────────────────────────────────────
@app.get("/")
def root():
    return {
        "service": "Calistheni API",
        "version": "1.0.0",
        "status": "running",
        "model": MODEL,
    }


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/generate")
async def generate(data: FormData, request: Request):
    log.info(f"[generate] skill={data.skill_cible} | freq={data.frequence_semaine} | ip={request.client.host}")

    prompt = build_prompt(data)

    try:
        response = mistral.chat.complete(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Tu es un coach calisthenics expert. "
                        "Tu réponds TOUJOURS et UNIQUEMENT avec du JSON valide, "
                        "sans aucun texte avant ou après."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=8000,
        )
    except Exception as e:
        log.error(f"[generate] Erreur Mistral API : {e}")
        raise HTTPException(status_code=502, detail=f"Erreur API Mistral : {str(e)}")

    raw = response.choices[0].message.content
    log.info(f"[generate] Réponse reçue ({len(raw)} caractères)")

    try:
        parsed = extract_json(raw)
        validated = validate_programme(parsed)
    except (json.JSONDecodeError, ValueError) as e:
        log.error(f"[generate] Parsing échoué : {e}\nRaw: {raw[:500]}")
        raise HTTPException(
            status_code=422,
            detail=f"La réponse IA n'est pas un JSON valide : {str(e)}",
        )

    log.info(f"[generate] Programme généré : {len(validated.get('programme', []))} semaines")
    return validated


# ─── Gestionnaire d'erreurs global ──────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.error(f"[error] Non géré : {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Erreur interne du serveur", "error": str(exc)},
    )


# ─── Entrypoint (local + Railway) ───────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
