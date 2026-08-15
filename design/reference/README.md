# Images de référence

Dépose ici les PNG générés, nommés comme indiqué dans `../07-restitution.md`.

Ce dossier est le seul endroit du dépôt où des images de travail sont attendues. Il
n'est pas embarqué dans l'exécutable : `build.py` ne collecte que `src/` et le cache
d'assets, donc ces fichiers ne coûtent rien au binaire livré.

Deux précautions :

- **Pas d'imagerie Riot.** Ni capture d'écran de jeu, ni artwork, ni portrait de
  champion, ni logo. Les maquettes doivent utiliser des ronds gris à la place des
  portraits, et un fond de jeu abstrait — les prompts le demandent déjà.
- **Des PNG, pas des JPEG.** Une palette prélevée sur du JPEG est faussée par la
  compression, et c'est exactement ce que je viens lire ici.
