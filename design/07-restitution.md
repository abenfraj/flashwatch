# 07 — Me rendre le résultat

Ce que je lis, et dans quel ordre, quand tu me dis « reproduis la direction *nom* ».

## 1. La charte, en premier

Un fichier `tokens-<direction>.md` à la racine de `design/`, contenant la réponse
texte de GPT telle quelle : la table de tokens, les nombres, la typographie, la
liste des effets, et si tu l'as demandée, la géométrie de la marque.

C'est **le fichier le plus important du dossier**. Les images me donnent une
intention ; la charte me donne des valeurs. Sans elle je devrais prélever des
couleurs à la pipette sur une image compressée, et une direction reproduite à la
pipette est une direction ratée de trois pour cent partout.

Si un champ manque ou reste vague, dis-le-moi plutôt que de le laisser vide : je
choisirai, mais je veux savoir que je choisis.

## 2. Les images

Dans `design/reference/`, en PNG, nommées ainsi :

```
<surface>-<variante>.png
```

| Nom attendu | Ce que c'est |
| --- | --- |
| `moodboard.png` | la planche d'ambiance de la direction |
| `states-cooldown.png` | la planche des six états d'un cooldown |
| `overlay-bar.png` | la barre chrono en jeu |
| `overlay-cards.png` | les cartes fixes en jeu |
| `overlay-rows.png` | les rangées compactes en jeu |
| `overlay-rest.png` | au repos et pendant le placement |
| `overlay-bright.png` | l'épreuve du fond clair |
| `menu-components.png` | la planche de composants |
| `menu-home.png` | la page d'accueil |
| `menu-display.png` | la page Affichage |
| `menu-dense.png` | réglages et dépannage |
| `menu-banner.png` | le bandeau de mise à jour |
| `guide-window.png` | le châssis du guide |
| `guide-figures.png` | la planche des six figures |
| `guide-stepper.png` | les variantes de compteur d'étapes |
| `mark-candidates.png` | les six candidats de marque |
| `mark-sizes.png` | l'épreuve des petites tailles |

Tout n'est pas obligatoire. Le minimum utile pour lancer une reproduction sérieuse :
`moodboard`, `states-cooldown`, `menu-components`, et la charte. Le reste affine.

Si tu as plusieurs essais d'une même image et que tu ne sais pas laquelle est la
bonne, garde-les toutes en suffixant `-a`, `-b`, `-c` et dis-moi laquelle tu préfères
— ou demande-moi de trancher, je te dirai laquelle est la plus reproductible, ce qui
n'est pas la même question que la plus belle.

## 3. Ce que je fais ensuite

Dans cet ordre, en te montrant le résultat avant de continuer :

1. Je réécris `src/theme.py` : palette, typographie, géométrie, feuille de style de
   la fenêtre. C'est le fichier qui décide de tout le reste.
2. Je réécris les thèmes de l'overlay dans `src/overlay.py` (`THEMES`), et je
   reprends les `paintEvent` des trois affichages selon la planche d'états.
3. Je reprends les figures du guide dans `src/onboarding.py`, en suivant le langage
   graphique de la planche des six figures.
4. Je reprends le cadre de zone OCR (`src/zone_overlay.py`) et le sélecteur de zone
   pour qu'ils suivent la même palette.
5. La marque, si elle change, dans les constantes `MARK_*` de `src/theme.py` — elle
   est dessinée par Qt *et* par Pillow au moment du build depuis ces mêmes nombres,
   donc une seule modification suffit.
6. `site/index.html`, pour que la page de téléchargement reste le même produit.
7. Je rends la revue visuelle en images, comme la précédente, pour que tu juges sans
   lancer l'application.

Ce que je **ne** ferai pas sans te le dire : changer les trois couleurs d'état
(neutre / bientôt / dispo) au point qu'elles cessent de se distinguer en combat, ou
adopter une police non libre. Dans ces deux cas je te proposerai l'alternative la
plus proche.

## 4. Si une maquette n'est pas reproductible

Ça arrivera au moins une fois. Je te dirai précisément quoi, pourquoi, et avec quoi
je propose de le remplacer — jamais une approximation silencieuse. Les trois cas les
plus probables, par ordre de fréquence :

- **un flou d'arrière-plan** sur l'overlay → remplacé par un fond plus opaque ou un
  dégradé, à choisir ;
- **une ombre portée** sur un panneau de la fenêtre → possible via un effet Qt, mais
  coûteuse ; en général remplacée par un filet clair sur l'arête haute ;
- **une police précise non libre** → remplacée par la plus proche sous licence OFL,
  avec le nom de celle que j'ai prise.
