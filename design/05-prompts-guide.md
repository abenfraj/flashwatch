# 05 — Le guide d'installation et ses six figures

Le guide est la surface la plus intéressante à faire redessiner, parce que ses
illustrations sont **peintes à la main** dans `src/onboarding.py` : rien n'est un
fichier image, tout est du `QPainter`. Une figure générée ici se traduit donc
littéralement en instructions de dessin — d'où l'insistance, dans les prompts, sur
« formes géométriques simples, aplats, traits, aucun rendu photographique ».

Les six figures, dans l'ordre du guide :

1. ce que fait le programme (le chat en bas, les timers en haut, une flèche)
2. le mode d'affichage de League (trois options, une seule possible)
3. la langue du client (la même annonce dans deux langues)
4. la zone du chat (un cadre vert, des repères dans la marge)
5. choisir et poser l'affichage (une copie fantôme ailleurs à l'écran)
6. où le programme vit ensuite (un coin de barre des tâches)

---

## 1. La fenêtre complète, pour le châssis

> **Le prompt est dans `prompts/05a-guide-fenetre.txt`** — ouvre le fichier, tout sélectionner, copier, coller dans ChatGPT.


**Comment juger :** le rapport entre la figure et le texte. Si la figure écrase le
texte, on ne lit plus rien ; si elle est timide, autant ne pas en faire.

---

## 2. Les six figures, sur une seule planche

Une planche unique est bien plus utile que six images séparées : elle force la
cohérence du langage graphique entre les figures, qui est précisément ce qui manque
aujourd'hui.

> **Le prompt est dans `prompts/05b-guide-six-figures.txt`** — ouvre le fichier, tout sélectionner, copier, coller dans ChatGPT.


**Comment juger :** posez-les côte à côte et demandez-vous si elles ont l'air
d'appartenir au même jeu de figures. Même épaisseur de trait, même façon de
représenter « un écran », mêmes flèches. C'est le seul critère qui compte ici.

---

## 3. Le compteur d'étapes, en détail

Petit élément, mais il est visible sur les six écrans et c'est un des rares endroits
où une direction peut s'exprimer gratuitement.

> **Le prompt est dans `prompts/05c-guide-stepper.txt`** — ouvre le fichier, tout sélectionner, copier, coller dans ChatGPT.


---

## 4. La marque, dans le contexte du guide *(facultatif)*

Si tu génères aussi la marque (`06-prompts-marque.md`), demande une variante de
l'en-tête du guide avec la nouvelle marque à sa place, pour vérifier qu'elle tient à
34 pixels à côté d'un titre.

> **Le prompt est dans `prompts/05d-guide-marque-entete.txt`** — ouvre le fichier, tout sélectionner, copier, coller dans ChatGPT.

