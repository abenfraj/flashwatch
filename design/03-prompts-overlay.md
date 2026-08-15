# 03 — Les trois affichages en jeu

C'est la surface qui compte. Elle est petite, elle est translucide, elle est posée
sur une scène de jeu qui bouge et qui change de luminosité, et on la lit en une
fraction de seconde. Une maquette jolie sur fond noir uni ne prouve rien : chaque
prompt ci-dessous demande donc un fond de jeu simulé.

Génère dans cet ordre. Le **1** est le plus utile de tous : c'est la planche
d'états, celle qui décide de tout le reste.

---

## 1. La planche d'états d'un cooldown *(à faire en premier)*

> **Le prompt est dans `prompts/03a-overlay-etats.txt`** — ouvre le fichier, tout sélectionner, copier, coller dans ChatGPT.


**Comment juger :** les six états doivent se distinguer **sans lire les libellés**.
Si « nearly back » et « ready » se ressemblent au premier coup d'œil, la direction
a un problème de couleurs d'état — redemande en imposant un écart de teinte.

---

## 2. La barre chrono, en jeu

> **Le prompt est dans `prompts/03b-overlay-barre.txt`** — ouvre le fichier, tout sélectionner, copier, coller dans ChatGPT.


**Comment juger :** le rail doit rester visible sur la partie la plus claire du
fond, et les chiffres doivent tenir sans halo. Si la maquette n'est lisible que
parce que le panneau est presque opaque, demande une version à 40 % d'opacité.

---

## 3. Les cartes fixes, en jeu

> **Le prompt est dans `prompts/03c-overlay-cartes.txt`** — ouvre le fichier, tout sélectionner, copier, coller dans ChatGPT.


**Comment juger :** l'anneau doit être lisible à petite taille. Trop fin il
disparaît, trop épais il mange le portrait — c'est le seul réglage vraiment délicat
de cet affichage, alors demande deux variantes d'épaisseur si le doute subsiste.

---

## 4. Les rangées compactes, en jeu

> **Le prompt est dans `prompts/03d-overlay-rangees.txt`** — ouvre le fichier, tout sélectionner, copier, coller dans ChatGPT.


---

## 5. Au repos, et pendant le placement

> **Le prompt est dans `prompts/03e-overlay-repos-placement.txt`** — ouvre le fichier, tout sélectionner, copier, coller dans ChatGPT.


**Comment juger :** l'état « au repos » est celui qu'on voit 90 % du temps. S'il
attire l'œil, c'est raté ; s'il est totalement invisible, l'utilisateur ne sait plus
si le programme tourne.

---

## 6. L'épreuve du fond clair *(optionnel mais révélateur)*

> **Le prompt est dans `prompts/03f-overlay-fond-clair.txt`** — ouvre le fichier, tout sélectionner, copier, coller dans ChatGPT.


**Comment juger :** c'est le test qui tue les directions trop claires ou trop peu
contrastées. Si les chiffres disparaissent, il faudra une ombre peinte sous le texte
(possible) ou un fond de panneau plus opaque (possible) — dis-le-moi dans la
restitution, je l'appliquerai.
