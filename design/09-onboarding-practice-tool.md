# 09 — L'onboarding en six écrans, réglé dans le Practice Tool

> **Les prompts sont dans `prompts/09-onboarding-ecrans.txt`** — six prompts, un par
> écran, à copier entre les lignes de séparation.

Ce parcours remplace celui que le programme fait aujourd'hui. La différence n'est pas
cosmétique : **tout se règle dans une vraie fenêtre de jeu** au lieu d'un bureau vide.

## Pourquoi le Practice Tool change tout

Le guide actuel place l'overlay sur le bureau avec de faux cooldowns, puis dit « ça
marchera en partie, promis ». C'est le maximum qu'on puisse faire hors du jeu, et
c'est faible : trois choses ne peuvent tout simplement pas être vérifiées là.

| Ce qu'on ne peut pas vérifier hors du jeu | Ce que le Practice Tool en fait |
| --- | --- |
| Le mode fenêtré sans bordure marche-t-il vraiment ? | L'overlay apparaît, ou il n'apparaît pas. Réponse immédiate. |
| La zone du chat est-elle bien trouvée ? | Il y a un vrai chat, à sa vraie place, à la bonne échelle d'interface. |
| La chaîne complète fonctionne-t-elle ? | On tape une ligne dans le chat, un timer apparaît. Bout en bout. |

Et il n'y a aucun enjeu : pas de coéquipiers qui attendent, pas de chronomètre, on
peut y rester dix minutes à déplacer une barre. C'est l'endroit exact où faire ça.

## Les six écrans

| # | Écran | Ce qu'il fait faire |
| --- | --- | --- |
| 1 | **Bienvenue** | Envoie l'utilisateur dans *Jouer → Entraînement → Outil d'entraînement*, avec le chemin dessiné. |
| 2 | **Fenêtré sans bordure** | Montre le réglage vidéo de League avec ses libellés exacts, une croix rouge sur *Plein écran*. |
| 3 | **Langue du client** | La même annonce dans les deux langues, côte à côte, et le sélecteur juste dessous. |
| 4 | **Choisir l'affichage** | Trois tuiles à gauche, et **le résultat qui s'affiche à l'écran de jeu à droite**, relié par un trait. |
| 5 | **Le poser** | L'affichage déverrouillé dans le jeu, des flèches, une copie fantôme ailleurs. |
| 6 | **La preuve** | On colle une ligne dans le chat, **un** timer apparaît. La chaîne entière, démontrée. |

L'écran final (« tout est prêt », l'icône dans la zone de notification) existe déjà
comme sixième figure de `05-prompts-guide.md` — inutile de le regénérer.

## Deux choses que ça implique dans le code

Les maquettes décrivent un comportement que le programme n'a pas encore. À faire
après le choix de direction, et ce n'est pas du décor :

1. **L'aperçu en direct au moment du choix.** Aujourd'hui choisir un affichage
   l'applique, mais il faut lancer le mode essai pour le voir. Sur l'écran 4, cliquer
   une tuile doit le faire apparaître à l'écran immédiatement, avec des cooldowns
   d'exemple. C'est le mode essai déclenché par le choix plutôt que par un bouton
   séparé — un bouton de moins, et la causalité devient évidente.
2. **Le guide sait si une partie est là.** Les écrans 4 à 6 n'ont de sens qu'avec un
   jeu à l'écran. Le guide doit donc afficher l'état : « Practice Tool détecté » ou
   « en attente d'une partie », et laisser passer quand même celui qui veut lire sans
   lancer League. `game_detector` sait déjà répondre à cette question ; il suffit de
   la poser.

Dis-le-moi quand tu veux que j'implémente ces deux-là : ce sont des changements de
comportement, pas de palette, donc ils sont indépendants de la direction artistique
retenue et peuvent se faire avant ou après.

## Sur la capture du réglage de League

Le prompt de l'écran 2 demande une **recréation schématique** aux libellés exacts du
client, pas une fausse capture d'écran. Deux raisons, et la seconde est la plus
pratique :

- une image qui imite l'interface d'un autre produit pose un problème d'image, et le
  programme se tient délibérément à distance de tout ce qui ressemble à l'identité de
  Riot ;
- une capture vieillit à chaque refonte du client et n'existe que dans une langue,
  alors qu'un diagramme aux bons mots — « Mode d'affichage », « Sans bordure » — reste
  navigable des années et se traduit avec le reste.

Si tu veux quand même une vraie capture, la bonne façon est que ce soit **la tienne**,
prise sur ton client, ajoutée à la main dans `design/reference/` — mais alors elle est
livrée dans l'exécutable, et il faudra décider si on assume de redistribuer une image
de l'interface de Riot. Le diagramme évite la question.
