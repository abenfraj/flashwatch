# 06 — La marque

Une seule forme, dessinée à quatre endroits : l'icône de la zone de notification
(16 px), l'icône de l'exécutable et de la barre des tâches, l'en-tête de la fenêtre
de contrôle (30 px) et celui du guide (34 px).

Deux contraintes structurent tout :

- **Elle doit tenir à 16 pixels.** C'est la taille du tray, et c'est là qu'une forme
  trop détaillée devient une bouillie. La marque actuelle est un disque sombre à
  liseré cyan avec deux aiguilles — la version précédente avait des traits d'un
  demi-pixel et pas de moyeu, et à 16 px elle ressemblait à un anneau taché.
- **Elle est redessinée par du code, deux fois** : par Qt à l'exécution et par
  Pillow au moment du build, depuis les *mêmes* nombres dans `src/theme.py`
  (`MARK_BOX`, `MARK_CENTRE`, `MARK_DISC_R`, `MARK_HANDS`…). Donc une marque
  utilisable ici est une marque **décrivable en géométrie** : cercles, arcs,
  segments, polygones. Pas un dégradé complexe, pas une illustration.

À ne pas oublier : rien qui puisse être confondu avec l'identité d'un jeu. Pas
d'imagerie hextech, pas de rune, pas d'épée, pas d'œil, pas de langage visuel
fantasy.

---

## 1. Des candidats

> **Le prompt est dans `prompts/06a-marque-candidats.txt`** — ouvre le fichier, tout sélectionner, copier, coller dans ChatGPT.


**Comment juger :** couvre chaque candidat avec le pouce à demi-fermé. Ce qui reste
identifiable à cette taille est ce qui tiendra à 16 px.

---

## 2. L'épreuve des petites tailles

À faire **avant** de choisir. C'est ce test qui élimine la moitié des candidats.

> **Le prompt est dans `prompts/06b-marque-tailles.txt`** — ouvre le fichier, tout sélectionner, copier, coller dans ChatGPT.


**Comment juger :** à 16 px, il faut que la silhouette et **une** couleur d'accent
suffisent à la reconnaître. Si le candidat n'existe que grâce à un détail intérieur,
il est éliminé, quelle que soit sa beauté en grand.

---

## 3. La géométrie, en chiffres

C'est la partie que je peux appliquer directement. Demande-la pour le candidat retenu.

> **Le prompt est dans `prompts/06c-marque-geometrie.txt`** — ouvre le fichier, tout sélectionner, copier, coller dans ChatGPT.


Colle cette réponse dans `tokens-<direction>.md` sous un titre « Marque » : c'est
exactement le format des constantes `MARK_*` de `src/theme.py`, et je peux les
remplacer sans interpréter.

---

## 4. La favicon du site *(facultatif)*

La page de téléchargement (`site/index.html`) porte la même marque en favicon et le
site est censé être le même produit que l'application. Si la marque change, elle
change là aussi — même géométrie, donc rien de plus à générer. À mentionner
simplement dans la restitution pour que je n'oublie pas de la mettre à jour.
