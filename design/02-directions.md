# 02 — Choisir une direction

Cinq directions volontairement éloignées les unes des autres. L'idée n'est pas
d'en explorer cinq : c'est d'en **choisir une** et de la pousser jusqu'au bout.
Une direction tiède appliquée partout donne exactement ce qu'on a aujourd'hui.

Lis les cinq descriptions, prends celle qui te parle, et colle le fichier de prompt
qui porte son nom dans `prompts/`. La description y est déjà incluse : il n'y a rien
à remplacer ni à recopier.

---

## A. Instrument de vol

Un cockpit en verre. Noir profond presque bleu, filets gravés d'un demi-pixel,
biseaux qui attrapent la lumière comme du métal brossé, **un seul** ambre de
signalisation et un cyan de veille. Chiffres condensés, alignés en colonnes,
graduations sur les rails. Les libellés sont de petites capitales espacées, comme
sérigraphiées sur un tableau de bord.

*Vocabulaire à donner à GPT :* glass cockpit, altimeter tape, engraved bezel,
silkscreened label, warning amber, instrument panel.

*Pourquoi ça marche ici :* le produit est un instrument de mesure. Le risque, c'est
la timidité — c'est déjà la famille de l'interface actuelle, il faut donc du
contraste franc, de vrais biseaux, des séparateurs gravés, pas des gris polis.

## B. Régie esport

L'habillage d'une diffusion. Chiffres gras, larges, légèrement italiques, blanc pur
sur noir dense. Des barres de couleur d'équipe posées en aplats, des pastilles
massives, des découpes diagonales qui suggèrent le mouvement. Rien de discret :
tout est fait pour être lu sur un flux compressé, à distance.

*Vocabulaire :* lower third, scoreboard bug, broadcast ticker, team colour bar,
extended bold numerals, diagonal cut.

*Pourquoi ça marche ici :* la lisibilité sous stress est exactement le problème que
la télé résout depuis cinquante ans. Le risque : sur un overlay permanent, le gras
peut devenir bruyant — il faudra demander une version « au repos » très sobre.

## C. Atelier d'horlogerie

Le programme est un chronomètre : autant l'assumer. Charbon chaud, laiton et acier,
un fond guilloché très discret, des index gravés autour des anneaux de progression,
des chiffres à empattements fins ou gravés. La couleur d'état arrive comme une
aiguille rouge sur un cadran : rare, donc lue.

*Vocabulaire :* guilloché, brushed brass, chronograph subdial, engraved index
marks, tachymeter bezel, warm charcoal, applied hands.

*Pourquoi ça marche ici :* c'est la direction qui *justifie* les anneaux de
progression au lieu de les décorer, et la plus singulière des cinq. Le risque :
la chaleur du laiton doit rester lisible par-dessus une scène de jeu bleutée.

## D. Terminal ambré

Monochrome. Ambre sur noir (ou vert sur noir), tout en chasse fixe, cadres
rectangulaires à filets simples, aucun dégradé, une trame de balayage à peine
perceptible. Les états ne changent pas de teinte mais d'**intensité** : veille,
normal, alerte pleine luminosité.

*Vocabulaire :* amber phosphor, VT terminal, scanline, monospaced grid, dim/bright
intensity, box-drawing rules.

*Pourquoi ça marche ici :* c'est ce qui coûte le moins cher à peindre, c'est
parfaitement lisible sur n'importe quel fond, et c'est immédiatement reconnaissable.
Le risque : le cliché. Il faut du vrai vocabulaire de terminal (colonnes, filets de
tableau, intensités) et pas juste « du vert qui brille ».

## E. Papier technique

Encre sur papier de calque, ou son négatif. Trame de grille au demi-ton, cotes et
repères de dessin industriel, annotations en chasse fixe, un seul rouge de
correction. Les portraits sont des cercles cerclés d'un trait fin, comme des
pièces référencées sur un plan.

*Vocabulaire :* blueprint, drafting grid, dimension lines, registration marks,
Swiss technical, halftone, single red annotation.

*Pourquoi ça marche ici :* personne ne fait ça sur un overlay de jeu, donc c'est
mémorable, et la rigueur du dessin technique sert la lisibilité. Le risque : sur un
jeu très clair, un panneau clair disparaît — cette direction impose un panneau plus
opaque, à demander explicitement.

---

## Le prompt de direction

À coller juste après le contexte. Il demande deux choses, dans cet ordre : une table
de jetons chiffrée — les 19 rôles de couleur que le code utilise réellement, les
rayons, les épaisseurs, les tailles, les licences de police — puis une planche
d'ambiance. **La table compte plus que l'image** : c'est elle que je peux appliquer
exactement.

> **Un fichier par direction, prêt à coller, la description déjà incluse :**
> `prompts/02-direction-instrument-de-vol.txt`, `…-regie-esport.txt`,
> `…-horlogerie.txt`, `…-terminal-ambre.txt`, `…-papier-technique.txt`.
> Il n'y a plus rien à remplacer : prends celui de la direction choisie.


## Après la réponse

Copie la table de tokens dans `tokens-<nom-de-la-direction>.md`, à la racine de ce
dossier — c'est le fichier que je lis en premier au moment de reproduire. Range la
planche d'ambiance dans `reference/` (voir `07-restitution.md` pour le nommage).

Si la réponse reste vague sur un point (« un gris chaud », « une police
géométrique »), redemande la valeur exacte avant de passer aux maquettes : chaque
approximation ici devient une décision arbitraire de ma part au moment du code.
