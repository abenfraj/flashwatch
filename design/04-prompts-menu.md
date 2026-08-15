# 04 — La fenêtre de contrôle

Une fenêtre de bureau classique, donc l'exercice est différent : ici on peut se
permettre des surfaces, de la matière et de la hiérarchie typographique, puisque
rien n'est posé sur un jeu et que rien ne se redessine dix fois par seconde.

Deux choses à savoir avant de générer :

- **Le texte reviendra faux.** C'est sans importance : les vraies chaînes viennent
  de `src/i18n.py`. Ce qu'on cherche, c'est la structure, la matière des cartes, le
  traitement de la navigation et des interrupteurs.
- **Les composants comptent plus que les pages.** Le prompt 1 (la planche de
  composants) est celui dont je tirerai le plus : Qt style les widgets un par un,
  donc une planche de composants se traduit presque directement en feuille de style.

---

## 1. La planche de composants *(à faire en premier)*

> **Le prompt est dans `prompts/04a-menu-composants.txt`** — ouvre le fichier, tout sélectionner, copier, coller dans ChatGPT.


**Comment juger :** l'interrupteur et la pastille d'état sont les deux composants
qui donnent le ton de toute la fenêtre. S'ils ressemblent aux composants par défaut
de n'importe quel framework, la direction n'a pas été poussée assez loin.

---

## 2. La page d'accueil

> **Le prompt est dans `prompts/04b-menu-accueil.txt`** — ouvre le fichier, tout sélectionner, copier, coller dans ChatGPT.


---

## 3. La page Affichage — celle du choix

> **Le prompt est dans `prompts/04c-menu-affichage.txt`** — ouvre le fichier, tout sélectionner, copier, coller dans ChatGPT.


**Comment juger :** les trois vignettes doivent être **lisibles à 112×54 pixels** —
c'est leur taille réelle. Si la maquette ne fonctionne qu'en grand, demande une
version « thumbnails only » agrandie pour voir ce qui survit à la réduction.

---

## 4. Les surfaces denses : réglages et dépannage

> **Le prompt est dans `prompts/04d-menu-dense.txt`** — ouvre le fichier, tout sélectionner, copier, coller dans ChatGPT.


---

## 5. Le bandeau de mise à jour *(petit mais visible)*

> **Le prompt est dans `prompts/04e-menu-bandeau.txt`** — ouvre le fichier, tout sélectionner, copier, coller dans ChatGPT.

