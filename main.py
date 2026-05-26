import json
import re
import os
import logging
import base64
import smtplib
import urllib.request
import urllib.error
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from mistralai import Mistral
from fpdf import FPDF

# ─── Logging ────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger(__name__)

# ─── App ────────────────────────────────────────────────────────
app = FastAPI(title="Calistheni API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://calistheni.com", "https://www.calistheni.com", "http://localhost", "http://127.0.0.1:5500"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY")
mistral = Mistral(api_key=MISTRAL_API_KEY) if MISTRAL_API_KEY else None
MODEL = os.environ.get("MISTRAL_MODEL", "mistral-small-latest")

# ─── Schémas ────────────────────────────────────────────────────
class FormData(BaseModel):
    skill_cible: str
    prerequis: dict = {}
    frequence_semaine: int
    duree_seance_min: int
    materiel: list[str]

class SendPDFRequest(BaseModel):
    email: str
    programme: dict

# ════════════════════════════════════════════════════════════════
# BIBLIOTHÈQUE D'EXERCICES — 100% déterministe, zéro LLM
# ════════════════════════════════════════════════════════════════

EXERCICES = {
    "Front Lever": {
        "debutant": [
            {"nom": "Dead Hang", "sets": 3, "duree_sec": 30, "reps": None, "repos_sec": 60, "conseil": "Epaules actives, pas de trapezes", "media_key": "dead_hang"},
            {"nom": "Scapular Pull-ups", "sets": 3, "duree_sec": None, "reps": 10, "repos_sec": 60, "conseil": "Mouvement des omoplates seulement", "media_key": "scapular_pull"},
            {"nom": "Tuck Front Lever Hold", "sets": 4, "duree_sec": 8, "reps": None, "repos_sec": 90, "conseil": "Retracter et deprimer les scapulas", "media_key": "tuck_front_lever"},
            {"nom": "Tuck Front Lever Raises", "sets": 3, "duree_sec": None, "reps": 6, "repos_sec": 90, "conseil": "Monter lentement depuis pendu", "media_key": "tuck_fl_raises"},
        ],
        "intermediaire": [
            {"nom": "Adv. Tuck Front Lever", "sets": 4, "duree_sec": 8, "reps": None, "repos_sec": 90, "conseil": "Hanches au niveau des epaules", "media_key": "adv_tuck_fl"},
            {"nom": "One Leg Front Lever", "sets": 3, "duree_sec": 10, "reps": None, "repos_sec": 90, "conseil": "Jambe tendue, corps rigide", "media_key": "one_leg_fl"},
            {"nom": "Front Lever Pulls", "sets": 3, "duree_sec": None, "reps": 5, "repos_sec": 120, "conseil": "Tirer les coudes vers les hanches", "media_key": "fl_pulls"},
            {"nom": "L-sit Pull-ups", "sets": 3, "duree_sec": None, "reps": 6, "repos_sec": 90, "conseil": "Maintenir le L pendant la traction", "media_key": "lsit_pull"},
        ],
        "avance": [
            {"nom": "Straddle Front Lever", "sets": 4, "duree_sec": 8, "reps": None, "repos_sec": 120, "conseil": "Ecarter les jambes pour reduire le levier", "media_key": "straddle_fl"},
            {"nom": "Front Lever Hold", "sets": 4, "duree_sec": 5, "reps": None, "repos_sec": 120, "conseil": "Corps parfaitement horizontal", "media_key": "front_lever"},
            {"nom": "Front Lever Raises", "sets": 3, "duree_sec": None, "reps": 4, "repos_sec": 120, "conseil": "Controle total montee et descente", "media_key": "fl_raises"},
            {"nom": "Weighted Pull-ups", "sets": 4, "duree_sec": None, "reps": 5, "repos_sec": 120, "conseil": "Lest progressif chaque semaine", "media_key": "weighted_pull"},
        ],
    },
    "Back Lever": {
        "debutant": [
            {"nom": "Skin the Cat", "sets": 3, "duree_sec": None, "reps": 5, "repos_sec": 90, "conseil": "Controle complet aller-retour", "media_key": "skin_cat"},
            {"nom": "Tuck Back Lever Hold", "sets": 4, "duree_sec": 10, "reps": None, "repos_sec": 90, "conseil": "Bras tendus, fessiers contractes", "media_key": "tuck_back_lever"},
            {"nom": "German Hang", "sets": 3, "duree_sec": 20, "reps": None, "repos_sec": 60, "conseil": "Progresser doucement en retroflexion", "media_key": "german_hang"},
            {"nom": "Pull-ups", "sets": 3, "duree_sec": None, "reps": 8, "repos_sec": 60, "conseil": "Full ROM, tete neutre", "media_key": "pull_up"},
        ],
        "intermediaire": [
            {"nom": "Half Lay Back Lever", "sets": 4, "duree_sec": 8, "reps": None, "repos_sec": 90, "conseil": "Une jambe tendue, une pliee", "media_key": "half_lay_bl"},
            {"nom": "Tuck Back Lever Raises", "sets": 3, "duree_sec": None, "reps": 6, "repos_sec": 90, "conseil": "Monter jusqu a horizontal", "media_key": "tuck_bl_raises"},
            {"nom": "Straddle Back Lever", "sets": 4, "duree_sec": 6, "reps": None, "repos_sec": 120, "conseil": "Jambes ecartees reduisent le levier", "media_key": "straddle_bl"},
            {"nom": "German Hang to Inverted", "sets": 3, "duree_sec": None, "reps": 5, "repos_sec": 90, "conseil": "Transition fluide et controlee", "media_key": "german_hang_inv"},
        ],
        "avance": [
            {"nom": "Full Back Lever Hold", "sets": 4, "duree_sec": 8, "reps": None, "repos_sec": 120, "conseil": "Corps rigide, bras perpendiculaires", "media_key": "back_lever"},
            {"nom": "Back Lever Raises", "sets": 3, "duree_sec": None, "reps": 5, "repos_sec": 120, "conseil": "Controle total sur toute la course", "media_key": "bl_raises"},
            {"nom": "Weighted Pull-ups", "sets": 4, "duree_sec": None, "reps": 5, "repos_sec": 120, "conseil": "Force de tirage supplementaire", "media_key": "weighted_pull"},
            {"nom": "Skin the Cat leste", "sets": 3, "duree_sec": None, "reps": 5, "repos_sec": 90, "conseil": "Ajouter lest progressivement", "media_key": "skin_cat_weighted"},
        ],
    },
    "Planche": {
        "debutant": [
            {"nom": "Frog Stand", "sets": 4, "duree_sec": 20, "reps": None, "repos_sec": 60, "conseil": "Poids vers l avant, equilibre", "media_key": "frog_stand"},
            {"nom": "Wrist Preparation", "sets": 3, "duree_sec": 30, "reps": None, "repos_sec": 45, "conseil": "Cercles et etirements poignets", "media_key": "wrist_prep"},
            {"nom": "Pseudo Planche Push-ups", "sets": 3, "duree_sec": None, "reps": 8, "repos_sec": 90, "conseil": "Doigts vers arriere, lean avant", "media_key": "pseudo_pl_pu"},
            {"nom": "Tuck Planche Hold", "sets": 4, "duree_sec": 8, "reps": None, "repos_sec": 90, "conseil": "Epaules devant les poignets", "media_key": "tuck_planche"},
        ],
        "intermediaire": [
            {"nom": "Adv. Tuck Planche Hold", "sets": 4, "duree_sec": 8, "reps": None, "repos_sec": 90, "conseil": "Dos presque horizontal", "media_key": "adv_tuck_planche"},
            {"nom": "Planche Lean", "sets": 4, "duree_sec": 20, "reps": None, "repos_sec": 60, "conseil": "Corps rigide, pencher progressivement", "media_key": "planche_lean"},
            {"nom": "Straddle Planche Hold", "sets": 3, "duree_sec": 5, "reps": None, "repos_sec": 120, "conseil": "Jambes ecartees au max", "media_key": "straddle_planche"},
            {"nom": "Pseudo Planche Push-ups lestes", "sets": 3, "duree_sec": None, "reps": 6, "repos_sec": 90, "conseil": "Progression du lean avant", "media_key": "pseudo_pl_weighted"},
        ],
        "avance": [
            {"nom": "Full Planche Hold", "sets": 4, "duree_sec": 5, "reps": None, "repos_sec": 120, "conseil": "Tout le corps horizontal et rigide", "media_key": "planche"},
            {"nom": "Planche Push-ups", "sets": 3, "duree_sec": None, "reps": 3, "repos_sec": 120, "conseil": "ROM complete, corps rigide", "media_key": "planche_pushup"},
            {"nom": "Straddle Planche Raises", "sets": 3, "duree_sec": None, "reps": 5, "repos_sec": 120, "conseil": "Monter depuis la position basse", "media_key": "straddle_pl_raises"},
            {"nom": "Planche Lean progressif", "sets": 4, "duree_sec": 25, "reps": None, "repos_sec": 90, "conseil": "Augmenter l angle chaque semaine", "media_key": "planche_lean_adv"},
        ],
    },
    "Muscle-Up": {
        "debutant": [
            {"nom": "Pull-ups explosifs", "sets": 4, "duree_sec": None, "reps": 6, "repos_sec": 90, "conseil": "Tirer fort, toucher la barre haut", "media_key": "explosive_pull"},
            {"nom": "Dips aux barres", "sets": 3, "duree_sec": None, "reps": 10, "repos_sec": 60, "conseil": "Descendre sous les coudes", "media_key": "dip"},
            {"nom": "False Grip Dead Hang", "sets": 3, "duree_sec": 15, "reps": None, "repos_sec": 60, "conseil": "Poignet sur la barre pas juste les doigts", "media_key": "false_grip"},
            {"nom": "Transition Practice", "sets": 4, "duree_sec": None, "reps": 5, "repos_sec": 90, "conseil": "Simuler le passage au dessus", "media_key": "mu_transition"},
        ],
        "intermediaire": [
            {"nom": "Kipping Muscle-up", "sets": 4, "duree_sec": None, "reps": 3, "repos_sec": 120, "conseil": "Elan hanche puis tirage vertical", "media_key": "kipping_mu"},
            {"nom": "Strict Pull-ups lestes", "sets": 4, "duree_sec": None, "reps": 6, "repos_sec": 90, "conseil": "Lest +5 a 10kg", "media_key": "weighted_pull"},
            {"nom": "Chest to Bar Pull-ups", "sets": 3, "duree_sec": None, "reps": 6, "repos_sec": 90, "conseil": "Poitrine touche la barre", "media_key": "chest_bar"},
            {"nom": "Ring Dips", "sets": 3, "duree_sec": None, "reps": 8, "repos_sec": 90, "conseil": "Anneaux stables en bas", "media_key": "ring_dip"},
        ],
        "avance": [
            {"nom": "Strict Muscle-up", "sets": 4, "duree_sec": None, "reps": 3, "repos_sec": 120, "conseil": "Aucun elan, force pure", "media_key": "strict_mu"},
            {"nom": "Weighted Muscle-up", "sets": 3, "duree_sec": None, "reps": 2, "repos_sec": 120, "conseil": "Gilet leste +5kg", "media_key": "weighted_mu"},
            {"nom": "L-sit Muscle-up", "sets": 3, "duree_sec": None, "reps": 2, "repos_sec": 120, "conseil": "Maintenir le L pendant le mouvement", "media_key": "lsit_mu"},
            {"nom": "Pull-ups lestes +20kg", "sets": 4, "duree_sec": None, "reps": 5, "repos_sec": 120, "conseil": "Force de base pour mu leste", "media_key": "heavy_pull"},
        ],
    },
    "Handstand": {
        "debutant": [
            {"nom": "Wrist Preparation", "sets": 3, "duree_sec": 30, "reps": None, "repos_sec": 45, "conseil": "Indispensable avant chaque seance", "media_key": "wrist_prep"},
            {"nom": "Crow Stand", "sets": 4, "duree_sec": 20, "reps": None, "repos_sec": 60, "conseil": "Regard entre les mains", "media_key": "crow_stand"},
            {"nom": "Wall Handstand Hold", "sets": 4, "duree_sec": 30, "reps": None, "repos_sec": 60, "conseil": "Dos au mur, corps droit", "media_key": "wall_hs"},
            {"nom": "Kick-ups mur", "sets": 4, "duree_sec": None, "reps": 6, "repos_sec": 60, "conseil": "Monter sans elan excessif", "media_key": "kickup"},
        ],
        "intermediaire": [
            {"nom": "Chest to Wall HS", "sets": 4, "duree_sec": 30, "reps": None, "repos_sec": 90, "conseil": "Ventre au mur, alignement parfait", "media_key": "chest_wall_hs"},
            {"nom": "Pirouette Balance", "sets": 3, "duree_sec": None, "reps": 8, "repos_sec": 60, "conseil": "Equilibre avec les doigts", "media_key": "pirouette"},
            {"nom": "Free Handstand Attempts", "sets": 5, "duree_sec": 10, "reps": None, "repos_sec": 60, "conseil": "Tolerer le desequilibre", "media_key": "free_hs"},
            {"nom": "HS Shoulder Shrugs", "sets": 3, "duree_sec": None, "reps": 10, "repos_sec": 60, "conseil": "Pousser le sol pour activer les epaules", "media_key": "hs_shrugs"},
        ],
        "avance": [
            {"nom": "Free Handstand 30s", "sets": 5, "duree_sec": 30, "reps": None, "repos_sec": 90, "conseil": "Maintenir sans mur", "media_key": "free_hs_30"},
            {"nom": "Handstand Push-ups", "sets": 3, "duree_sec": None, "reps": 5, "repos_sec": 90, "conseil": "Tete touche le sol", "media_key": "hspu"},
            {"nom": "Handstand Walking", "sets": 3, "duree_sec": 15, "reps": None, "repos_sec": 90, "conseil": "Petits pas lateraux", "media_key": "hs_walk"},
            {"nom": "Press Handstand Negative", "sets": 3, "duree_sec": None, "reps": 4, "repos_sec": 120, "conseil": "Descendre lentement en straddle", "media_key": "press_hs_neg"},
        ],
    },
    "Dragon Flag": {
        "debutant": [
            {"nom": "Hollow Body Hold", "sets": 4, "duree_sec": 20, "reps": None, "repos_sec": 60, "conseil": "Bas du dos plaque au sol", "media_key": "hollow_body"},
            {"nom": "Tuck Dragon Flag", "sets": 4, "duree_sec": 8, "reps": None, "repos_sec": 90, "conseil": "Epaules restent au sol", "media_key": "tuck_dragon_flag"},
            {"nom": "Dragon Flag Negative", "sets": 4, "duree_sec": None, "reps": 5, "repos_sec": 90, "conseil": "Descendre en 5 secondes", "media_key": "df_negative"},
            {"nom": "Leg Raises", "sets": 3, "duree_sec": None, "reps": 10, "repos_sec": 60, "conseil": "Jambes tendues, lombaires protegees", "media_key": "leg_raises"},
        ],
        "intermediaire": [
            {"nom": "One Leg Dragon Flag", "sets": 4, "duree_sec": 8, "reps": None, "repos_sec": 90, "conseil": "Une jambe tendue, une pliee", "media_key": "one_leg_df"},
            {"nom": "Dragon Flag Hold", "sets": 4, "duree_sec": 6, "reps": None, "repos_sec": 120, "conseil": "Corps rigide comme une planche", "media_key": "dragon_flag"},
            {"nom": "Windshield Wipers", "sets": 3, "duree_sec": None, "reps": 8, "repos_sec": 90, "conseil": "Rotation controlee des hanches", "media_key": "windshield"},
            {"nom": "L-sit Hold", "sets": 3, "duree_sec": 15, "reps": None, "repos_sec": 60, "conseil": "Compression abdominale maximale", "media_key": "l_sit"},
        ],
        "avance": [
            {"nom": "Full Dragon Flag", "sets": 4, "duree_sec": None, "reps": 5, "repos_sec": 120, "conseil": "Montee et descente controlees", "media_key": "dragon_flag_full"},
            {"nom": "Dragon Flag leste", "sets": 3, "duree_sec": None, "reps": 4, "repos_sec": 120, "conseil": "Cheville lestee +2.5kg", "media_key": "df_weighted"},
            {"nom": "Hanging Leg Raises lestes", "sets": 3, "duree_sec": None, "reps": 8, "repos_sec": 90, "conseil": "Pas de balancement", "media_key": "hlr_weighted"},
            {"nom": "Hollow Body Rocks", "sets": 3, "duree_sec": None, "reps": 15, "repos_sec": 60, "conseil": "Position maintenue pendant les rocks", "media_key": "hollow_rocks"},
        ],
    },
    "Human Flag": {
        "debutant": [
            {"nom": "Side Lever Tuck", "sets": 4, "duree_sec": 8, "reps": None, "repos_sec": 90, "conseil": "Bras tendus, corps lateral", "media_key": "side_lever_tuck"},
            {"nom": "Human Flag Negative", "sets": 4, "duree_sec": None, "reps": 4, "repos_sec": 90, "conseil": "Descendre lentement depuis vertical", "media_key": "hf_negative"},
            {"nom": "Push-Pull Isometrique", "sets": 3, "duree_sec": 15, "reps": None, "repos_sec": 90, "conseil": "Pousser bas, tirer haut sur la barre", "media_key": "push_pull_iso"},
            {"nom": "Pull-ups", "sets": 3, "duree_sec": None, "reps": 10, "repos_sec": 60, "conseil": "Force de tirage de base", "media_key": "pull_up"},
        ],
        "intermediaire": [
            {"nom": "Tuck Human Flag", "sets": 4, "duree_sec": 8, "reps": None, "repos_sec": 90, "conseil": "Hanches au niveau des epaules", "media_key": "tuck_human_flag"},
            {"nom": "One Leg Human Flag", "sets": 3, "duree_sec": 6, "reps": None, "repos_sec": 120, "conseil": "Jambe du bas tendue", "media_key": "one_leg_hf"},
            {"nom": "Dips lestes", "sets": 3, "duree_sec": None, "reps": 8, "repos_sec": 90, "conseil": "Force de poussee supplementaire", "media_key": "weighted_dip"},
            {"nom": "Side Plank dynamique", "sets": 3, "duree_sec": None, "reps": 10, "repos_sec": 60, "conseil": "Rotation lente des hanches", "media_key": "side_plank_dyn"},
        ],
        "avance": [
            {"nom": "Full Human Flag", "sets": 4, "duree_sec": 5, "reps": None, "repos_sec": 120, "conseil": "Corps parfaitement horizontal", "media_key": "human_flag"},
            {"nom": "Human Flag Raises", "sets": 3, "duree_sec": None, "reps": 4, "repos_sec": 120, "conseil": "Monter depuis bas jusqu horizontal", "media_key": "hf_raises"},
            {"nom": "Weighted Pull-ups +20kg", "sets": 4, "duree_sec": None, "reps": 5, "repos_sec": 120, "conseil": "Force maximale de tirage", "media_key": "heavy_pull"},
            {"nom": "Human Flag bilat", "sets": 3, "duree_sec": 5, "reps": None, "repos_sec": 120, "conseil": "Travailler les deux cotes egalement", "media_key": "hf_bilateral"},
        ],
    },
    "One Arm Pull-Up": {
        "debutant": [
            {"nom": "Pull-ups strict", "sets": 4, "duree_sec": None, "reps": 10, "repos_sec": 90, "conseil": "Base solide avant tout", "media_key": "pull_up"},
            {"nom": "Archer Pull-ups", "sets": 4, "duree_sec": None, "reps": 6, "repos_sec": 90, "conseil": "Bras d aide de plus en plus tendu", "media_key": "archer_pull"},
            {"nom": "One Arm Dead Hang", "sets": 3, "duree_sec": 10, "reps": None, "repos_sec": 60, "conseil": "Chaque bras alternativement", "media_key": "one_arm_hang"},
            {"nom": "Pull-ups lestes +10kg", "sets": 3, "duree_sec": None, "reps": 6, "repos_sec": 90, "conseil": "Construire la force de base", "media_key": "weighted_pull"},
        ],
        "intermediaire": [
            {"nom": "Archer Pull-ups lestes", "sets": 4, "duree_sec": None, "reps": 5, "repos_sec": 90, "conseil": "Bras aide presque tendu", "media_key": "weighted_archer"},
            {"nom": "One Arm Assisted Negative", "sets": 4, "duree_sec": None, "reps": 4, "repos_sec": 120, "conseil": "Descendre en 5 sec, aide minimale", "media_key": "one_arm_neg"},
            {"nom": "Pull-ups lestes +20kg", "sets": 4, "duree_sec": None, "reps": 5, "repos_sec": 120, "conseil": "Force maximale requise", "media_key": "heavy_pull"},
            {"nom": "Towel Pull-ups", "sets": 3, "duree_sec": None, "reps": 6, "repos_sec": 90, "conseil": "Renforcement de la prise", "media_key": "towel_pull"},
        ],
        "avance": [
            {"nom": "One Arm Pull-up Assisted", "sets": 4, "duree_sec": None, "reps": 3, "repos_sec": 120, "conseil": "Bande de resistance legere seulement", "media_key": "oaup_assisted"},
            {"nom": "One Arm Negative strict", "sets": 4, "duree_sec": None, "reps": 3, "repos_sec": 120, "conseil": "Descente en 8 secondes", "media_key": "one_arm_strict_neg"},
            {"nom": "Full One Arm Pull-up", "sets": 3, "duree_sec": None, "reps": 2, "repos_sec": 120, "conseil": "Mouvement complet un bras", "media_key": "one_arm_pu"},
            {"nom": "Pull-ups lestes +30kg", "sets": 3, "duree_sec": None, "reps": 3, "repos_sec": 120, "conseil": "Force brute pour progresser", "media_key": "max_pull"},
        ],
    },
}

JOURS_SEMAINE = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]

OBJECTIFS = {
    "debutant":      "Construire les bases et la force scapulaire",
    "intermediaire": "Consolider les progressions et allonger le levier",
    "avance":        "Maximiser le temps de hold et la force specifique",
}

# ════════════════════════════════════════════════════════════════
# LOGIQUE DETERMINISTE
# ════════════════════════════════════════════════════════════════

def evaluer_niveau(prerequis: dict) -> str:
    """Evalue le niveau depuis les prérequis sans LLM."""
    if not prerequis:
        return "debutant"
    oui = sum(1 for v in prerequis.values() if v == "oui")
    en_cours = sum(1 for v in prerequis.values() if v == "en_cours")
    total = len(prerequis)
    score = (oui * 2 + en_cours) / (total * 2) if total > 0 else 0
    if score >= 0.7:
        return "avance"
    elif score >= 0.35:
        return "intermediaire"
    return "debutant"


def niveau_to_texte(niveau: str, skill: str) -> str:
    textes = {
        "debutant":      f"Debutant en {skill} — fondations a construire",
        "intermediaire": f"Intermediaire en {skill} — progressions en cours",
        "avance":        f"Avance en {skill} — peaufinage du skill final",
    }
    return textes.get(niveau, f"Niveau {niveau} en {skill}")


def build_programme(data: FormData) -> dict:
    """Construit le programme 100% déterministe depuis la bibliothèque."""
    skill = data.skill_cible
    niveau = evaluer_niveau(data.prerequis)
    exercices_dispo = EXERCICES.get(skill, {}).get(niveau, [])

    # Filtrer selon matériel si nécessaire
    # (simplification : on garde tout, le coach ajuste en live)
    max_ex_per_seance = 4
    n_seances = min(data.frequence_semaine, 6)

    seances = []
    for i in range(n_seances):
        jour = JOURS_SEMAINE[i] if n_seances <= 7 else f"Seance {i+1}"
        # Rotation des exercices selon le jour
        start = (i * 2) % len(exercices_dispo) if exercices_dispo else 0
        exs = []
        for j in range(min(max_ex_per_seance, len(exercices_dispo))):
            ex = exercices_dispo[(start + j) % len(exercices_dispo)]
            exs.append({
                "id": ex["media_key"],
                "nom": ex["nom"],
                "sets": ex["sets"],
                "reps": ex["reps"],
                "duree_sec": ex["duree_sec"],
                "repos_sec": ex["repos_sec"],
                "conseil": ex["conseil"],
                "media_key": ex["media_key"],
            })
        seances.append({"jour": jour, "exercices": exs})

    return {
        "skill_target": skill,
        "niveau_actuel": niveau_to_texte(niveau, skill),
        "programme": [{
            "semaine": 1,
            "objectif": OBJECTIFS.get(niveau, "Progresser vers le skill cible"),
            "seances": seances,
        }]
    }


# ─── Personnalisation LLM ────────────────────────────────────────
def personnaliser_programme(programme: dict, data: FormData) -> dict:
    if not mistral:
        return programme
    skill = data.skill_cible
    niveau = programme["niveau_actuel"]
    prereq_str = ", ".join(k + ":" + v for k, v in data.prerequis.items()) or "non renseignes"
    noms = []
    for seance in programme["programme"][0]["seances"]:
        for ex in seance["exercices"]:
            if ex["nom"] not in noms:
                noms.append(ex["nom"])
    sep = chr(10) + "    "
    conseils_keys = sep.join(chr(34) + n + chr(34) + ": " + chr(34) + "conseil court ici" + chr(34) for n in noms)
    prompt = (
        "Tu es coach calisthenics. Reponds UNIQUEMENT en JSON valide." + chr(10)
        + "Skill: " + skill + chr(10)
        + "Niveau: " + niveau + chr(10)
        + "Prerequis: " + prereq_str + chr(10)
        + "Frequence: " + str(data.frequence_semaine) + "x/semaine" + chr(10)
        + "Retourne ce JSON:" + chr(10)
        + "{" + chr(10)
        + '  "objectif": "une phrase sur lobjectif de la semaine",' + chr(10)
        + '  "conseils": {' + chr(10)
        + "    " + conseils_keys + chr(10)
        + "  }" + chr(10)
        + "}"
    )
    try:
        response = mistral.chat.complete(
            model=MODEL,
            messages=[
                {"role": "system", "content": "Reponds UNIQUEMENT en JSON valide, aucun texte autour."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.4,
            max_tokens=600,
        )
        raw = response.choices[0].message.content.strip()
        brace_start = raw.find("{")
        brace_end = raw.rfind("}") + 1
        if brace_start == -1:
            return programme
        perso = json.loads(raw[brace_start:brace_end])
        if "objectif" in perso:
            programme["programme"][0]["objectif"] = perso["objectif"]
        conseils = perso.get("conseils", {})
        for seance in programme["programme"][0]["seances"]:
            for ex in seance["exercices"]:
                if ex["nom"] in conseils:
                    ex["conseil"] = conseils[ex["nom"]]
        log.info("[generate] Personnalisation LLM OK")
    except Exception as e:
        log.warning("[generate] LLM ignore: " + str(e))
    return programme


# ─── Route generate ─────────────────────────────────────────────
@app.post("/generate")
async def generate(data: FormData, request: Request):
    log.info(f"[generate] skill={data.skill_cible} | frequence={data.frequence_semaine}")
    try:
        # 1. Structure 100% deterministe
        programme = build_programme(data)

        # 2. Personnalisation LLM sur les textes uniquement
        programme = personnaliser_programme(programme, data)

        return programme
    except Exception as e:
        log.error(f"[generate] Erreur: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════════
# PDF + EMAIL
# ════════════════════════════════════════════════════════════════

def clean(text: str) -> str:
    if not text:
        return ""
    replacements = {
        "\u2014": "-", "\u2013": "-", "\u2019": "'", "\u2018": "'",
        "\u201c": '"', "\u201d": '"', "\u00e9": "e", "\u00e8": "e",
        "\u00ea": "e", "\u00e0": "a", "\u00e2": "a", "\u00f4": "o",
        "\u00fb": "u", "\u00f9": "u", "\u00ee": "i", "\u00ef": "i",
        "\u00e7": "c", "\u00c9": "E", "\u00c0": "A", "\u2026": "...",
        "\u00b0": "deg", "\u00d7": "x", "\u2192": "->",
    }
    for orig, repl in replacements.items():
        text = text.replace(orig, repl)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def generate_pdf(programme: dict) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    skill = clean(programme.get("skill_target", "").upper())
    niveau = clean(programme.get("niveau_actuel", "-"))

    # Header
    pdf.set_fill_color(20, 20, 20)
    pdf.rect(0, 0, 210, 42, "F")
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 22, "", ln=True)
    pdf.cell(0, 14, f"CALISTHENI - {skill}", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(180, 180, 180)
    pdf.cell(0, 8, niveau, ln=True, align="C")
    pdf.ln(8)

    for week in programme.get("programme", []):
        objectif = clean(week.get("objectif", ""))
        pdf.set_fill_color(232, 99, 42)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 10, f"  SEMAINE {week.get('semaine', 1)}  -  {objectif}", ln=True, fill=True)
        pdf.ln(3)

        for seance in week.get("seances", []):
            jour = clean(seance.get("jour", "")).upper()
            pdf.set_fill_color(235, 235, 235)
            pdf.set_text_color(30, 30, 30)
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(0, 8, f"  {jour}", ln=True, fill=True)
            pdf.ln(2)

            for ex in seance.get("exercices", []):
                nom = clean(ex.get("nom", ""))
                conseil = clean(ex.get("conseil", ""))
                sets = ex.get("sets", "")
                reps = ex.get("reps")
                dur = ex.get("duree_sec")
                repos = ex.get("repos_sec", "")
                vol = f"{dur}s" if dur else f"{reps} reps"

                pdf.set_text_color(20, 20, 20)
                pdf.set_font("Helvetica", "B", 10)
                pdf.cell(0, 6, f"    {nom}", ln=True)
                pdf.set_font("Helvetica", "", 9)
                pdf.set_text_color(80, 80, 80)
                pdf.cell(0, 5, f"    {sets} x {vol}  |  repos {repos}s", ln=True)
                if conseil:
                    pdf.set_font("Helvetica", "I", 8)
                    pdf.set_text_color(130, 130, 130)
                    pdf.cell(0, 5, f"    -> {conseil}", ln=True)
                pdf.ln(2)
            pdf.ln(3)

    pdf.set_y(-18)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(160, 160, 160)
    pdf.cell(0, 8, "Genere par calistheni.com", align="C")

    return bytes(pdf.output())


def send_email_with_pdf(to_email: str, programme: dict, pdf_bytes: bytes):
    api_key = os.environ.get("BREVO_API_KEY")
    if not api_key:
        raise ValueError("BREVO_API_KEY manquante")

    skill = programme.get("skill_target", "Programme")
    filename = f"programme_{skill.lower().replace(' ', '_')}.pdf"
    pdf_b64 = base64.b64encode(pdf_bytes).decode()
    sender_email = os.environ.get("BREVO_SENDER_EMAIL", "noreply@calistheni.com")

    payload = json.dumps({
        "sender": {"name": "Calistheni", "email": sender_email},
        "to": [{"email": to_email}],
        "subject": f"Ton programme {skill} - Calistheni",
        "htmlContent": f"""
        <div style="font-family:sans-serif;max-width:520px;margin:0 auto;padding:40px 32px;background:#0d0d0d;border-radius:12px;">
          <h1 style="color:#fff;font-size:24px;margin:0 0 8px;">Ton programme est pret !</h1>
          <p style="color:#999;margin:0 0 16px;">Skill : <strong style="color:#e8632a">{skill}</strong></p>
          <p style="color:#ccc;line-height:1.7;">Programme en piece jointe. Suis la progression et reviens quand tu maitrises ce skill.</p>
          <p style="color:#555;font-size:13px;margin-top:24px;">Tarik - calistheni.com</p>
        </div>""",
        "attachment": [{"name": filename, "content": pdf_b64}]
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=payload,
        headers={"accept": "application/json", "api-key": api_key, "content-type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read())
            log.info(f"[send_pdf] Envoye a {to_email} | id={result.get('messageId')}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        log.error(f"[send_pdf] Brevo error {e.code}: {body}")
        raise ValueError(f"Brevo {e.code}: {body}")


@app.post("/send-pdf")
async def send_pdf(req: SendPDFRequest, request: Request):
    log.info(f"[send_pdf] email={req.email}")
    try:
        pdf_bytes = generate_pdf(req.programme)
        send_email_with_pdf(req.email, req.programme, pdf_bytes)
        return {"success": True, "message": f"Programme envoye a {req.email}"}
    except Exception as e:
        log.error(f"[send_pdf] Erreur: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Santé ──────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"service": "Calistheni API", "version": "2.0.0", "status": "running"}

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.error(f"[error] {exc}")
    return JSONResponse(status_code=500, content={"detail": str(exc)})

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
