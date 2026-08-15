# 08 — La maquette HTML : dessiner en CSS, livrer en Qt

**L'application reste une application de bureau.** Elle ne devient pas une page
web, elle n'embarque pas de navigateur, elle continue de se dessiner elle-même en
Qt. Le HTML/CSS sert d'**atelier** : c'est là qu'on décide à quoi ça ressemble,
parce que c'est là que c'est instantané et gratuit. Le résultat est ensuite porté
dans `src/theme.py` et les `paintEvent`.

Pourquoi ne pas simplement livrer du HTML dans l'app : voir la fin de ce fichier,
avec les chiffres mesurés. En deux mots — l'exécutable passerait de 98 à environ
180 Mo et l'overlay ferait tourner un moteur Chromium par-dessus le jeu.

## Le fichier

`design/maquette/index.html` — un seul fichier, aucune dépendance, aucun serveur.
**Double-clic pour l'ouvrir.** Il contient :

| Section | Ce qu'elle sert |
| --- | --- |
| 01 La palette | tous les jetons, avec leur valeur **lue depuis la feuille de style** — une étiquette ne peut donc pas mentir sur ce qui est appliqué |
| 02 Les six états d'un cooldown | la planche qui décide de la lisibilité en combat |
| 03 Les trois affichages sur le jeu | avec un basculeur **fond moyen / sombre / clair** |
| 04 La fenêtre de contrôle | la page Affichage, vignettes à leur taille réelle (112 × 54) |
| 05 Les composants isolés | boutons, interrupteurs, champs, pastilles, readouts |
| 06 Le guide | en-tête, figure, compteur d'étapes, pied |

Tout est piloté par **une trentaine de variables CSS** en haut du fichier. Chacune
porte le nom de la constante correspondante dans `src/theme.py` ou des clés
`THEMES` de `src/overlay.py` :

```css
--fw-field:   #0a0c11;   /* → theme.py : FIELD    */
--fw-accent:  #5ac8ff;   /* → theme.py : SIGNAL   */
--fw-ready:   #6ee28e;   /* → overlay THEMES["ready"] */
```

C'est tout l'intérêt : le portage devient une **traduction ligne à ligne** au lieu
d'une interprétation. Pas de pipette sur une image compressée, pas de « à peu près
ce bleu-là ».

## Ce qu'il a montré en une minute, et ce qui en est sorti

À sa première ouverture, la maquette portait encore la palette sombre. Bascule sur
**fond clair**, section 03 : le compte à rebours blanc `4:42` devenait presque
illisible — un panneau translucide sombre posé sur un fond très clair donne un gris
moyen, et du texte blanc sur gris moyen ne tient pas. Contraste mesuré : **3,56:1**.

C'est ce qui a décidé la direction actuelle. Le programme est passé en **clair
partout** : panneau quasi opaque (0,80 au lieu de 0,42), chiffres foncés, halo clair
au lieu d'une ombre noire. Le même texte est maintenant à **plus de 10:1 sur les
trois fonds**. Les jetons de cette maquette portent cette palette : c'est le point de
départ, pas une cible.

## La boucle

1. **Ouvre le fichier**, regarde, bascule les trois fonds.
2. **Modifie les variables** en haut — dans n'importe quel éditeur de texte,
   `Ctrl+S`, `F5`. Tu vois le résultat sur les six surfaces d'un coup.
3. Ou bien **fais-le faire à GPT** : colle `01-contexte.md`, puis le prompt
   ci-dessous avec le fichier entier. Il te rend le fichier restylé.
4. **Garde ce que tu aimes**, jette le reste, recommence. C'est gratuit.
5. Quand c'est bon : garde le fichier, et dis-moi **« reproduis la maquette »**.
   Je lis les variables, je porte, je te rends la revue en images.

## Le prompt de restylage

> **Le prompt est dans `prompts/08-restyler-la-maquette.txt`** — ouvre le fichier, tout sélectionner, copier, coller dans ChatGPT.


## Et si on livrait vraiment du HTML dans l'app ?

Mesuré sur cette machine, dans le venv du projet :

| | |
| --- | --- |
| `Qt6WebEngineCore.dll` | **195,3 Mo** |
| `icudtl.dat` + ressources `.pak` | ~26 Mo |
| Total à embarquer | **~341 Mo** non compressés |
| Exécutable actuel | **98,5 Mo** |
| Exécutable estimé avec un moteur web | **~180 Mo** |

`build.py` exclut déjà explicitement `QtWebEngine`, `QtQuick`, `QtQml` et l'OpenGL
logiciel, avec ce commentaire : *« QtWebEngine alone is over 100 MB »*. Et le poids
n'est même pas le pire :

- **La RAM.** Un moteur Chromium, c'est un processus de rendu et un processus GPU en
  plus, soit 100 à 150 Mo à lui seul. Le budget documenté du programme est *sous*
  200 Mo au total.
- **L'overlay.** Il doit être translucide, cliquable-à-travers, toujours au-dessus,
  redessiné dix fois par seconde par-dessus un jeu en plein écran sans bordure, sous
  3 % de CPU. Aujourd'hui c'est six cercles et six nombres tracés au `QPainter`.
  Faire composer ça par un moteur web pendant qu'un jeu tourne, c'est risquer des
  saccades **dans le jeu** — le pire défaut possible pour ce produit précis.
- **Ce que ça achèterait.** Le flou d'arrière-plan, `box-shadow`, les transitions.
  Trois choses, dont aucune ne sert un overlay qu'on lit en une fraction de seconde
  et qui ne connaît même pas le survol de souris.

Tout le reste de ce qui fait qu'une interface a l'air dessinée — palette, échelle
typographique, rythme d'espacement, rayons, dégradés, états, ombres peintes — existe
à l'identique en Qt. La maquette de ce dossier en est la démonstration : elle est en
CSS et elle ne contient rien que le code ne puisse reproduire.
