"""Hand-written text templates in every supported language, for mock mode
(MATCHHEALTH_MOCK_LLM=1) and the Narrator's fallback.

The real agents write natively per language through the model. These
templates are what viewers see when the model isn't used (the scheduled
demo job, tests) or fails: real translations of a fixed set of sentences,
filled with facts from the engine. Unknown languages fall back to English.
"""

from __future__ import annotations

LANGS = ("en", "es", "fr", "pt", "de")


def lang_of(lang: str) -> str:
    return lang if lang in LANGS else "en"


def ordinal(n: int, lang: str) -> str:
    lang = lang_of(lang)
    if lang == "en":
        return {1: "1st", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")
    if lang == "fr":
        return "1er" if n == 1 else f"{n}e"
    if lang == "de":
        return f"{n}."
    return f"{n}.º"


# Score separator: German writes 2:1.
SEP = {"en": "-", "es": "-", "fr": "-", "pt": "-", "de": ":"}
POINTS = {"en": ("point", "points"), "es": ("punto", "puntos"), "fr": ("point", "points"),
          "pt": ("ponto", "pontos"), "de": ("Punkt", "Punkten")}

# Foul descriptions (thresholds.FOUL_TYPES). German is dative: it follows "nach".
FOULS = {
    "a late challenge": {"es": "una entrada tardía", "fr": "un tacle en retard",
                         "pt": "uma entrada atrasada", "de": "einem zu späten Einsteigen"},
    "a reckless tackle": {"es": "una entrada temeraria", "fr": "un tacle imprudent",
                          "pt": "uma entrada imprudente", "de": "einem rücksichtslosen Tackling"},
    "a trip": {"es": "una zancadilla", "fr": "un croche-pied", "pt": "uma rasteira",
               "de": "einem Beinstellen"},
    "a shirt pull": {"es": "un tirón de camiseta", "fr": "un tirage de maillot",
                     "pt": "um puxão de camisa", "de": "einem Trikotzupfen"},
    "a mistimed challenge": {"es": "una entrada mal calculada",
                             "fr": "une intervention mal maîtrisée",
                             "pt": "uma entrada mal calculada",
                             "de": "einem schlecht getimten Tackling"},
    "a foul in the build-up": {"es": "una falta en la jugada",
                               "fr": "une faute dans la construction",
                               "pt": "uma falta na saída de bola",
                               "de": "einem Foul im Spielaufbau"},
}
CARD = {"en": {"yellow": "Yellow", "red": "Red"}, "es": {"yellow": "amarilla", "red": "roja"},
        "fr": {"yellow": "jaune", "red": "rouge"}, "pt": {"yellow": "amarelo", "red": "vermelho"},
        "de": {"yellow": "Gelbe", "red": "Rote"}}

KINDS = {
    "en": {"goal": "goal", "big_chance": "big chance", "control_swing": "momentum swing",
           "pressing_spell": "pressing spell", "speed_milestone": "thunderbolt shot",
           "foul": "card", "pass_quality": "pass under pressure"},
    "es": {"goal": "gol", "big_chance": "gran ocasión", "control_swing": "cambio de dominio",
           "pressing_spell": "fase de presión", "speed_milestone": "disparo potentísimo",
           "foul": "tarjeta", "pass_quality": "pase bajo presión"},
    "fr": {"goal": "but", "big_chance": "grosse occasion",
           "control_swing": "renversement de domination",
           "pressing_spell": "temps fort de pressing",
           "speed_milestone": "frappe surpuissante", "foul": "carton",
           "pass_quality": "passe sous pression"},
    "pt": {"goal": "gol", "big_chance": "grande chance", "control_swing": "virada de domínio",
           "pressing_spell": "blitz de pressão", "speed_milestone": "chute fortíssimo",
           "foul": "cartão", "pass_quality": "passe sob pressão"},
    "de": {"goal": "Tor", "big_chance": "Großchance", "control_swing": "Kontrollwechsel",
           "pressing_spell": "Pressingphase", "speed_milestone": "Gewaltschuss",
           "foul": "Karte", "pass_quality": "Pass unter Druck"},
}

# --- overlays: (casual headline, analyst headline, subline or None) -------------

OVERLAY = {
    "en": {
        "goal": ("{scorer} nets one for {team}!", "Goal: {scorer} ({team})", None),
        "goal_sub1": "First goal of the season", "goal_subn": "Goal number {n} this season",
        "big_chance": ("Huge chance for {team}!", "Big chance for {team}: xG {q}", None),
        "control_swing": ("{team} are running the show", "{team} take control: {f} to {t}",
                          "Control score up from {f} to {t}"),
        "pressing_spell": ("{team}'s press is wrecking the rhythm",
                           "{team} press forces {n} turnovers in 5 min",
                           "{n} turnovers in 5 minutes"),
        "speed_milestone": ("Screamer from {player}!", "{player} shot at {kmh} km/h", None),
        "foul_yellow": "{player} picks up a yellow for {foul}",
        "foul_red": "{player} sees red for {foul}",
        "foul_analyst": "{card} card: {player} ({team})", "foul_sub": "Free kick to {fouled}",
        "pass_quality": ("{player} slices open the defence!",
                         "{player}: {dist}m pass, difficulty {diff}", None),
        "pressured": "Played under pressure",
    },
    "es": {
        "goal": ("¡{scorer} marca para {team}!", "Gol: {scorer} ({team})", None),
        "goal_sub1": "Su primer gol de la temporada",
        "goal_subn": "Su gol número {n} de la temporada",
        "big_chance": ("¡Ocasión enorme para {team}!", "Gran ocasión de {team}: xG {q}", None),
        "control_swing": ("{team} domina el partido", "{team} toma el control: de {f} a {t}",
                          "El control sube de {f} a {t}"),
        "pressing_spell": ("La presión de {team} rompe el ritmo rival",
                           "La presión de {team} fuerza {n} pérdidas en 5 min",
                           "{n} pérdidas forzadas en 5 minutos"),
        "speed_milestone": ("¡Misil de {player}!", "Disparo de {player} a {kmh} km/h", None),
        "foul_yellow": "{player} ve la amarilla por {foul}",
        "foul_red": "{player} ve la roja por {foul}",
        "foul_analyst": "Tarjeta {card}: {player} ({team})", "foul_sub": "Tiro libre para {fouled}",
        "pass_quality": ("¡{player} abre la defensa!",
                         "{player}: pase de {dist} m, dificultad {diff}", None),
        "pressured": "Bajo presión",
    },
    "fr": {
        "goal": ("{scorer} marque pour {team} !", "But : {scorer} ({team})", None),
        "goal_sub1": "Premier but de la saison", "goal_subn": "{n}e but de la saison",
        "big_chance": ("Énorme occasion pour {team} !", "Grosse occasion pour {team} : xG {q}",
                       None),
        "control_swing": ("{team} prend les commandes", "{team} prend le contrôle : de {f} à {t}",
                          "Indice de contrôle de {f} à {t}"),
        "pressing_spell": ("Le pressing de {team} casse le rythme",
                           "Le pressing de {team} force {n} pertes en 5 min",
                           "{n} ballons récupérés en 5 minutes"),
        "speed_milestone": ("Quelle frappe de {player} !", "Frappe de {player} à {kmh} km/h",
                            None),
        "foul_yellow": "Carton jaune pour {player} après {foul}",
        "foul_red": "Carton rouge pour {player} après {foul}",
        "foul_analyst": "Carton {card} : {player} ({team})", "foul_sub": "Coup franc pour {fouled}",
        "pass_quality": ("{player} transperce la défense !",
                         "{player} : passe de {dist} m, difficulté {diff}", None),
        "pressured": "Sous pression",
    },
    "pt": {
        "goal": ("{scorer} marca pelo {team}!", "Gol: {scorer} ({team})", None),
        "goal_sub1": "Primeiro gol na temporada", "goal_subn": "{n}º gol na temporada",
        "big_chance": ("Chance enorme para o {team}!", "Grande chance do {team}: xG {q}", None),
        "control_swing": ("{team} manda no jogo", "{team} assume o controle: de {f} para {t}",
                          "Índice de controle sobe de {f} para {t}"),
        "pressing_spell": ("A pressão do {team} quebra o ritmo",
                           "Pressão do {team} força {n} perdas em 5 min",
                           "{n} bolas recuperadas em 5 minutos"),
        "speed_milestone": ("Que pancada de {player}!", "Chute de {player} a {kmh} km/h", None),
        "foul_yellow": "{player} leva amarelo por {foul}",
        "foul_red": "{player} é expulso por {foul}",
        "foul_analyst": "Cartão {card}: {player} ({team})", "foul_sub": "Falta para o {fouled}",
        "pass_quality": ("{player} rasga a defesa!",
                         "{player}: passe de {dist} m, dificuldade {diff}", None),
        "pressured": "Sob pressão",
    },
    "de": {
        "goal": ("{scorer} trifft für {team}!", "Tor: {scorer} ({team})", None),
        "goal_sub1": "Erstes Saisontor", "goal_subn": "Saisontor Nummer {n}",
        "big_chance": ("Riesenchance für {team}!", "Großchance für {team}: xG {q}", None),
        "control_swing": ("{team} hat das Spiel im Griff",
                          "{team} übernimmt die Kontrolle: {f} auf {t}",
                          "Kontrollwert steigt von {f} auf {t}"),
        "pressing_spell": ("Das Pressing von {team} bricht den Rhythmus",
                           "Pressing von {team}: {n} Ballgewinne in 5 Min.",
                           "{n} erzwungene Ballverluste in 5 Minuten"),
        "speed_milestone": ("Was für ein Hammer von {player}!",
                            "Schuss von {player} mit {kmh} km/h", None),
        "foul_yellow": "Gelb für {player} nach {foul}",
        "foul_red": "Rot für {player} nach {foul}",
        "foul_analyst": "{card} Karte: {player} ({team})", "foul_sub": "Freistoß für {fouled}",
        "pass_quality": ("{player} zerlegt die Abwehr!",
                         "{player}: {dist}-m-Pass, Schwierigkeit {diff}", None),
        "pressured": "Unter Druck",
    },
}


def overlay_text(kind: str, team: str, player: str | None, facts: dict, mode: str,
                 lang: str) -> tuple[str, str | None]:
    """(headline, subline) for one moment in one persona's mode and language."""
    lang = lang_of(lang)
    T = OVERLAY[lang]
    analyst = mode == "analyst"
    v = {"team": team, "player": player or team, "scorer": facts.get("scorer") or player,
         "q": facts.get("shot_quality"), "kmh": facts.get("shot_speed_kmh"),
         "f": facts.get("control_from"), "t": facts.get("control_to"),
         "n": facts.get("turnovers_forced_5min"), "dist": facts.get("pass_distance_m"),
         "diff": facts.get("pass_difficulty")}
    if kind == "foul":
        card = facts.get("card", "yellow")
        foul = facts.get("foul_type", "")
        v.update(card=CARD[lang].get(card, card),
                 foul=foul if lang == "en" else FOULS.get(foul, {}).get(lang, foul),
                 fouled=facts.get("fouled_team", ""))
        head = T["foul_analyst"] if analyst else T["foul_red" if card == "red" else "foul_yellow"]
        return head.format(**v), T["foul_sub"].format(**v)
    casual, analyst_head, sub = T[kind]
    head = (analyst_head if analyst else casual).format(**v)
    if kind == "goal" and facts.get("scorer_season_goals"):
        n = facts["scorer_season_goals"]
        sub = T["goal_sub1"] if n == 1 else T["goal_subn"].format(n=n)
    elif kind == "pass_quality" and facts.get("under_pressure"):
        sub = T["pressured"]
    return head, (sub.format(**v) if sub else None)


# --- Narrator: storylines, checkpoints, recap ------------------------------------

NARRATIVE = {
    "en": {
        "pm_title": "Matchweek {mw}: the storylines",
        "pm_table": "{h} ({hp}) host {a} ({ap}), {gap} {points} apart in the table.",
        "pm_team": "{team}: {pos} on {pts} pts (xG {xf} for, {xa} against).",
        "unbeaten": "{team} are unbeaten in {n}. Can they keep it going?",
        "winless": "{team} haven't won in {n}. Something has to give.",
        "unbeaten_a": "{team}: unbeaten in {n} (form {form}).",
        "winless_a": "{team}: winless in {n} (form {form}).",
        "form": "Recent form: {h} {hf}, {a} {af}.",
        "scorer": "Watch {p}: {g} goals this season for {team}.",
        "scorer_a": "{p} ({team}): {g} league goals so far.",
        "clash": "Style clash: {hs} vs {as_}.",
        "prev": "Earlier this season: {home} {s0}{sep}{s1} {away}.",
        "level": "Still level at {h}{sep}{a}.", "lead": "{team} lead {x}{sep}{y}.",
        "latest_goal": "Latest goal: {p} for {team} at {clock}.",
        "latest_moment": "Latest key moment: {kind} for {team} at {clock}.",
        "quiet": "A quiet start: no key moments yet.",
        "control_a": "Control {hc}–{ac}, xG {hx}–{ax}, shots {hs}–{as_}.",
        "on_top": "{team} have had more control.",
        "even": "Neither side has taken control yet.",
        "labels": {"15'": "15'", "Half-time": "Half-time", "60'": "60'"},
        "cp_title": "{label}: {h} {hg}{sep}{ag} {a}",
        "ft_title": "Full time: {h} {hg}{sep}{ag} {a}",
        "home_win": "{h} take all three points.", "away_win": "{a} win away from home.",
        "draw": "The points are shared.",
        "ft_a": "{h} {hg}{sep}{ag} {a}, xG {hx}–{ax}.",
        "goals": "Goals: {list}.", "no_goals": "No goals.",
        "ft_stats": "Shots {hs}–{as_}, control at the whistle {hc}–{ac}.",
        "standout": "Standout: {p} ({team}).",
        "table": "Table: {h} now {hp}, {a} {ap}.",
    },
    "es": {
        "pm_title": "Jornada {mw}: las claves",
        "pm_table": "{h} ({hp}) recibe a {a} ({ap}), a {gap} {points} en la tabla.",
        "pm_team": "{team}: {pos} con {pts} pts (xG {xf} a favor, {xa} en contra).",
        "unbeaten": "{team} lleva {n} partidos sin perder. ¿Seguirá la racha?",
        "winless": "{team} suma {n} partidos sin ganar. Algo tiene que cambiar.",
        "unbeaten_a": "{team}: {n} sin perder (forma {form}).",
        "winless_a": "{team}: {n} sin ganar (forma {form}).",
        "form": "Forma reciente: {h} {hf}, {a} {af}.",
        "scorer": "Atención a {p}: {g} goles esta temporada con {team}.",
        "scorer_a": "{p} ({team}): {g} goles en liga.",
        "clash": "Choque de estilos entre {h} y {a}.",
        "prev": "En la ida: {home} {s0}{sep}{s1} {away}.",
        "level": "Empate a {h}.", "lead": "{team} gana {x}{sep}{y}.",
        "latest_goal": "Último gol: {p} ({team}) en el {clock}.",
        "latest_moment": "Última jugada clave: {kind} de {team} en el {clock}.",
        "quiet": "Inicio tranquilo: aún sin jugadas clave.",
        "control_a": "Control {hc}–{ac}, xG {hx}–{ax}, tiros {hs}–{as_}.",
        "on_top": "{team} domina el juego.",
        "even": "Ningún equipo se ha hecho con el control.",
        "labels": {"15'": "Minuto 15", "Half-time": "Descanso", "60'": "Minuto 60"},
        "cp_title": "{label}: {h} {hg}{sep}{ag} {a}",
        "ft_title": "Final: {h} {hg}{sep}{ag} {a}",
        "home_win": "{h} se lleva los tres puntos.", "away_win": "{a} gana a domicilio.",
        "draw": "Reparto de puntos.",
        "ft_a": "{h} {hg}{sep}{ag} {a}, xG {hx}–{ax}.",
        "goals": "Goles: {list}.", "no_goals": "Sin goles.",
        "ft_stats": "Tiros {hs}–{as_}, control al final {hc}–{ac}.",
        "standout": "Destacado: {p} ({team}).",
        "table": "Clasificación: {h} queda {hp}, {a} {ap}.",
    },
    "fr": {
        "pm_title": "Journée {mw} : les enjeux",
        "pm_table": "{h} ({hp}) reçoit {a} ({ap}), avec {gap} {points} d'écart au classement.",
        "pm_team": "{team} : {pos} avec {pts} pts (xG {xf} pour, {xa} contre).",
        "unbeaten": "{team} reste sur {n} matchs sans défaite. La série va-t-elle durer ?",
        "winless": "{team} n'a plus gagné depuis {n} matchs. Il faut que ça change.",
        "unbeaten_a": "{team} : {n} matchs sans défaite (forme {form}).",
        "winless_a": "{team} : {n} matchs sans victoire (forme {form}).",
        "form": "Forme récente : {h} {hf}, {a} {af}.",
        "scorer": "À suivre : {p}, {g} buts cette saison avec {team}.",
        "scorer_a": "{p} ({team}) : {g} buts en championnat.",
        "clash": "Choc de styles entre {h} et {a}.",
        "prev": "Match aller : {home} {s0}{sep}{s1} {away}.",
        "level": "Toujours à égalité, {h}{sep}{a}.", "lead": "{team} mène {x}{sep}{y}.",
        "latest_goal": "Dernier but : {p} pour {team} à {clock}.",
        "latest_moment": "Dernière action clé : {kind} pour {team} à {clock}.",
        "quiet": "Début calme : pas encore d'action clé.",
        "control_a": "Contrôle {hc}–{ac}, xG {hx}–{ax}, tirs {hs}–{as_}.",
        "on_top": "{team} a davantage le contrôle.",
        "even": "Aucune équipe n'a encore pris le contrôle.",
        "labels": {"15'": "15e minute", "Half-time": "Mi-temps", "60'": "60e minute"},
        "cp_title": "{label} : {h} {hg}{sep}{ag} {a}",
        "ft_title": "Fin du match : {h} {hg}{sep}{ag} {a}",
        "home_win": "{h} empoche les trois points.", "away_win": "{a} s'impose à l'extérieur.",
        "draw": "Les points sont partagés.",
        "ft_a": "{h} {hg}{sep}{ag} {a}, xG {hx}–{ax}.",
        "goals": "Buts : {list}.", "no_goals": "Pas de but.",
        "ft_stats": "Tirs {hs}–{as_}, contrôle au coup de sifflet {hc}–{ac}.",
        "standout": "Homme du match : {p} ({team}).",
        "table": "Classement : {h} désormais {hp}, {a} {ap}.",
    },
    "pt": {
        "pm_title": "Rodada {mw}: as histórias do jogo",
        "pm_table": "{h} ({hp}) recebe o {a} ({ap}), com {gap} {points} de diferença na tabela.",
        "pm_team": "{team}: {pos} com {pts} pts (xG {xf} a favor, {xa} contra).",
        "unbeaten": "{team} está invicto há {n} jogos. Vai manter a sequência?",
        "winless": "{team} não vence há {n} jogos. Algo precisa mudar.",
        "unbeaten_a": "{team}: {n} jogos sem perder (forma {form}).",
        "winless_a": "{team}: {n} jogos sem vencer (forma {form}).",
        "form": "Fase recente: {h} {hf}, {a} {af}.",
        "scorer": "De olho em {p}: {g} gols na temporada pelo {team}.",
        "scorer_a": "{p} ({team}): {g} gols no campeonato.",
        "clash": "Choque de estilos entre {h} e {a}.",
        "prev": "No primeiro turno: {home} {s0}{sep}{s1} {away}.",
        "level": "Segue empatado em {h}{sep}{a}.", "lead": "{team} vence por {x}{sep}{y}.",
        "latest_goal": "Último gol: {p} para o {team} aos {clock}.",
        "latest_moment": "Último lance importante: {kind} do {team} aos {clock}.",
        "quiet": "Começo morno: nenhum lance importante ainda.",
        "control_a": "Controle {hc}–{ac}, xG {hx}–{ax}, finalizações {hs}–{as_}.",
        "on_top": "{team} tem mais controle do jogo.",
        "even": "Nenhum time assumiu o controle ainda.",
        "labels": {"15'": "15 minutos", "Half-time": "Intervalo", "60'": "60 minutos"},
        "cp_title": "{label}: {h} {hg}{sep}{ag} {a}",
        "ft_title": "Fim de jogo: {h} {hg}{sep}{ag} {a}",
        "home_win": "{h} fica com os três pontos.", "away_win": "{a} vence fora de casa.",
        "draw": "Os pontos são divididos.",
        "ft_a": "{h} {hg}{sep}{ag} {a}, xG {hx}–{ax}.",
        "goals": "Gols: {list}.", "no_goals": "Sem gols.",
        "ft_stats": "Finalizações {hs}–{as_}, controle no apito final {hc}–{ac}.",
        "standout": "Destaque: {p} ({team}).",
        "table": "Tabela: {h} agora em {hp}, {a} em {ap}.",
    },
    "de": {
        "pm_title": "{mw}. Spieltag: die Geschichten",
        "pm_table": ("{h} (Platz {hpn}) empfängt {a} (Platz {apn}), "
                     "mit {gap} {points} Abstand in der Tabelle."),
        "pm_team": "{team}: Platz {posn} mit {pts} Pkt. (xG {xf} für, {xa} gegen).",
        "unbeaten": "{team} ist seit {n} Spielen ungeschlagen. Hält die Serie?",
        "winless": "{team} wartet seit {n} Spielen auf einen Sieg. Etwas muss sich ändern.",
        "unbeaten_a": "{team}: {n} Spiele ungeschlagen (Form {form}).",
        "winless_a": "{team}: {n} Spiele ohne Sieg (Form {form}).",
        "form": "Aktuelle Form: {h} {hf}, {a} {af}.",
        "scorer": "Achtung auf {p}: {g} Saisontore für {team}.",
        "scorer_a": "{p} ({team}): bisher {g} Ligatore.",
        "clash": "Stil-Duell zwischen {h} und {a}.",
        "prev": "Hinspiel: {home} {s0}{sep}{s1} {away}.",
        "level": "Es steht weiter {h}{sep}{a}.", "lead": "{team} führt {x}{sep}{y}.",
        "latest_goal": "Letztes Tor: {p} für {team} ({clock}).",
        "latest_moment": "Letzte Schlüsselszene: {kind} für {team} ({clock}).",
        "quiet": "Ruhiger Beginn: noch keine Schlüsselszenen.",
        "control_a": "Kontrolle {hc}–{ac}, xG {hx}–{ax}, Schüsse {hs}–{as_}.",
        "on_top": "{team} hat mehr Kontrolle.",
        "even": "Noch hat keine Mannschaft die Kontrolle übernommen.",
        "labels": {"15'": "15. Minute", "Half-time": "Halbzeit", "60'": "60. Minute"},
        "cp_title": "{label}: {h} {hg}{sep}{ag} {a}",
        "ft_title": "Abpfiff: {h} {hg}{sep}{ag} {a}",
        "home_win": "{h} holt die drei Punkte.", "away_win": "{a} gewinnt auswärts.",
        "draw": "Punkteteilung.",
        "ft_a": "{h} {hg}{sep}{ag} {a}, xG {hx}–{ax}.",
        "goals": "Tore: {list}.", "no_goals": "Keine Tore.",
        "ft_stats": "Schüsse {hs}–{as_}, Kontrolle beim Abpfiff {hc}–{ac}.",
        "standout": "Herausragend: {p} ({team}).",
        "table": "Tabelle: {h} jetzt auf Platz {hpn}, {a} auf Platz {apn}.",
    },
}
