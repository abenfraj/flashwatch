# Kit de direction artistique

Ce dossier sert à **faire dessiner l'interface ailleurs, puis à la reproduire ici**.
Le programme est fonctionnel et testé ; ce qui manque, c'est un parti pris visuel.

L'application **reste une application de bureau** : elle continue de se dessiner
elle-même en Qt, elle n'embarque pas de navigateur. Le HTML/CSS de ce dossier est un
**atelier**, pas le produit — voir `08-maquette-html.md` pour les chiffres qui
tranchent la question (un moteur web ferait passer l'exécutable de 98 à ~180 Mo et
ferait composer l'overlay par Chromium par-dessus le jeu).

## Le plus simple : `A-DEPOSER-DANS-CHATGPT.md`

**Un seul fichier, à glisser dans ChatGPT.** Il contient tout : le produit, les
surfaces, les limites techniques, les cinq directions et douze tâches numérotées. Il
commence par dire au modèle de tout lire, de ne rien exécuter, et d'attendre — ensuite
tu demandes « tâche 1 », « tâche 2 », etc.

Ce n'est pas la concaténation des fichiers ci-dessous : les règles communes y sont
énoncées **une seule fois** au lieu de quinze, et la séquence est explicite, sinon le
modèle tente d'exécuter les douze tâches d'un coup. Pour la tâche 12, joins aussi
`maquette/index.html`.

## Sinon, un prompt à la fois : `prompts/`

**Un fichier `.txt` = un prompt à coller.** Ouvre, `Ctrl+A`, `Ctrl+C`, colle dans
ChatGPT — rien à modifier, rien à compléter. Commence par
**`prompts/00-LIRE-DABORD.txt`**, qui donne l'ordre en une page. Utile si tu veux
travailler surface par surface, ou reprendre une seule maquette plus tard.

Les fichiers `.md` numérotés de ce dossier ne contiennent plus les prompts, mais ce
qui ne se colle pas : pourquoi chaque maquette est demandée, et **comment juger** ce
qui revient. Les `.txt` sont la version qui part dans ChatGPT ; les `.md` sont la
version qu'on lit.

## Deux chemins, et lequel prendre

**Le chemin court, recommandé : `08-maquette-html.md`.** Le fichier
`maquette/index.html` contient déjà toutes les surfaces du programme, dessinées en
CSS et pilotées par une trentaine de variables portant le nom des constantes de
`src/theme.py`. Tu l'ouvres d'un double-clic, tu changes les variables — ou tu le
fais restyler par GPT en un prompt — et tu vois les six surfaces changer d'un coup.
C'est plus rapide et plus fidèle qu'une image : rien à prélever à la pipette, les
valeurs sont déjà exactes, et rien de ce qu'il contient n'est irreproductible en Qt.

**Le chemin long, pour l'inspiration : les prompts d'images, `01-` à `06-`.** Une
image reste meilleure qu'une maquette pour une chose : trouver une direction quand
on n'en a aucune. Une planche d'ambiance, une matière, un traitement de chiffres.
Sers-t'en pour décider *où* aller, puis applique-le dans la maquette HTML.

## La boucle, par les images

1. **`prompts/01-contexte.txt`** en premier message d'une conversation ChatGPT. Il
   décrit le produit, les surfaces à habiller et les limites techniques. Tout ce
   qui suit s'appuie dessus.
2. **Choisir une direction** : lis les cinq descriptions dans `02-directions.md`,
   puis colle `prompts/02-direction-<nom>.txt`. GPT répond par une charte chiffrée —
   palette en hexadécimal, typographie, rayons, épaisseurs — *et* une planche
   d'ambiance. La charte compte plus que l'image : c'est elle que je peux appliquer
   exactement.
3. **Générer les maquettes** avec `prompts/03*` à `prompts/06*`, dans l'ordre de
   priorité indiqué plus bas. Une image par prompt, plusieurs essais par image.
4. **Déposer le résultat** dans `reference/` en respectant le nommage de
   `07-restitution.md`, coller la charte dans `tokens-<direction>.md`.
5. **Me dire** : « reproduis la direction *nom* ». Je lis les images et la charte,
   et je réécris `theme.py` + les `paintEvent` en conséquence.

> Les modèles d'images ne savent pas écrire du texte propre ni placer un pixel au
> pixel près. Ce n'est pas un problème : on ne leur demande pas une spécification,
> on leur demande **une palette, des formes, une texture, une hiérarchie**. Le
> texte reviendra probablement massacré — ignore-le, les vraies chaînes viennent
> de `src/i18n.py` au moment de la reproduction.

## Les surfaces, par priorité

| # | Surface | Fichier de prompts | Pourquoi cette priorité |
| --- | --- | --- | --- |
| 1 | **Les trois affichages en jeu** (barre chrono, cartes fixes, rangées compactes) | `03-prompts-overlay.md` | C'est le produit. C'est ce qu'on regarde en combat, et la seule surface qui doive survivre à un fond d'écran de jeu chargé. |
| 2 | **La fenêtre de contrôle** (en-tête, navigation, 4 pages) | `04-prompts-menu.md` | La première impression après l'installation. |
| 3 | **Le guide d'installation** (6 étapes, 6 figures dessinées) | `05-prompts-guide.md` | Les figures sont peintes à la main : une bonne direction ici se voit tout de suite. |
| 3b | **Le nouveau parcours d'onboarding**, réglé dans le Practice Tool | `09-onboarding-practice-tool.md` | Six écrans qui remplacent le guide actuel : une vraie fenêtre de jeu au lieu d'un bureau vide. |
| 4 | **La marque** (icône du tray, en-têtes) | `06-prompts-marque.md` | Une seule forme, dessinée trois fois dans le code — à ne changer qu'une fois la direction arrêtée. |
| 5 | Le cadre de zone OCR, le sélecteur de zone | *(couverts par la charte)* | Utilitaires, ils suivent la palette sans maquette dédiée. |

Les quatre premières sont déjà présentes dans `maquette/index.html`, ce qui permet de
les juger ensemble plutôt qu'une par une — c'est là que les incohérences se voient.

## Ce qui est déjà là

Le programme est **clair**, depuis la décision de le passer en clair partout :
fond `#eef1f6`, cartes blanches, accent `#06699f`, et un overlay clair quasi opaque
à chiffres foncés. Deux palettes vivent dans `src/theme.py` (`light` et `dark`) avec
`ACTIVE = "light"` ; les trois thèmes d'overlay (`light`, `dark`, `neon`) sont dans
`src/overlay.py`, chacun avec sa propre opacité.

Ce n'est pas une contrainte de style mais un résultat mesuré : un panneau sombre à
42 % posé sur un jeu très clair fait tomber le chiffre blanc à **3,56:1**, tandis
qu'un panneau clair à 80 % tient **au-delà de 10:1 sur les trois fonds**. Toute la
palette passe 4,5:1 contre ses deux fonds, ratios en commentaire dans le code.

Ce qu'une direction artistique peut donc faire, et ne pas faire :

- **Elle change tout le reste** : la matière des surfaces, la typographie, les
  rayons, les textures, le rythme, la marque. C'est là que le caractère manque.
- **Elle reste claire.** Repasser au sombre annulerait le seul réglage du produit
  qui a été démontré plutôt que choisi.
- **Elle garde trois couleurs d'état distinguables** (« bientôt », « dispo », le
  neutre). Elles *veulent dire quelque chose* ; une direction qui les noie coûte de
  la lisibilité en combat, ce qui est le seul critère non négociable.
- Elle s'applique aussi à `site/index.html`, qui doit rester le même produit.

## Contraintes non négociables

Détaillées dans `CONTRAINTES-QT.md`, résumées ici parce qu'elles décident de ce
qui est demandable :

- **Aucune imagerie Riot.** Ni artwork, ni logo, ni portrait de champion, ni
  police du client. Le programme est délibérément non-affilié ; les maquettes
  utilisent des ronds gris à la place des portraits.
- **Pas de flou d'arrière-plan.** Qt n'a pas de `backdrop-filter` : un panneau
  translucide qui floute le jeu derrière lui n'est pas reproductible.
- **Pas d'ombre en QSS.** `box-shadow` et `text-shadow` n'existent pas dans les
  feuilles de style Qt. Une ombre est possible mais doit être *peinte*, donc
  demandée explicitement et avec parcimonie.
- **L'overlay se redessine 10 fois par seconde par-dessus un jeu**, sous 3 % de
  CPU. Tout effet coûteux par image est exclu.
- **Une police personnalisée doit être libre** (SIL OFL ou Apache-2.0) pour être
  embarquée dans l'exécutable.
