# Ce qui est reproductible, et ce qui ne l'est pas

Référence technique du kit. À lire avant d'accepter une maquette : une image
magnifique qui repose sur un flou d'arrière-plan ou une ombre CSS est une image
qu'on ne peut pas livrer, et on ne le découvre qu'au moment du code.

Tout est dessiné avec **PySide6 (Qt 6)**, de deux façons :

- **QPainter** pour l'overlay, les figures du guide, le cadre de zone OCR et les
  vignettes d'affichage : du dessin impératif, donc très libre.
- **Qt Style Sheets (QSS)** pour les widgets de la fenêtre de bureau : une syntaxe
  qui *ressemble* à CSS et qui n'en est pas.

---

## Disponible, et utilisé sans hésiter

| Effet | Comment c'est construit |
| --- | --- |
| Aplats, dégradés linéaires, radiaux, coniques | `qlineargradient` / `qradialgradient` / `qconicalgradient` en QSS ; `QLinearGradient` & co. en peinture |
| Transparence par pixel | canal alpha de `QColor`, et `WA_TranslucentBackground` sur l'overlay |
| Coins arrondis, y compris différents par coin | `border-radius` en QSS ; `QPainterPath.addRoundedRect` en peinture |
| Anneaux, arcs, secteurs, jauges | `drawArc`, `drawPie`, `QPen` avec `setCapStyle` |
| Filets, pointillés, tirets | `QPen` + `setDashPattern` |
| Découpe à une forme quelconque | `setClipPath` (c'est ainsi que les portraits sont ronds) |
| Ombres et halos **peints** | un deuxième tracé décalé et translucide sous le premier ; c'est déjà ce que fait le compte à rebours de l'overlay |
| Superpositions translucides | plusieurs passes de peinture, alphas cumulés |
| Textures géométriques (grille, guilloché, hachures, trame) | boucle de `drawLine` / `drawEllipse`, à graver une fois dans un `QPixmap` puis à réutiliser |
| Interlignage des capitales | `letter-spacing` en QSS — **vérifié : fonctionne** (une étiquette passe de 88 à 133 px) |
| États des widgets | pseudo-états `:hover`, `:checked`, `:focus`, `:disabled` |
| Pièces internes des widgets | sous-contrôles `::indicator`, `::handle`, `::groove`, `::drop-down`… — c'est comme ça que les cases à cocher sont dessinées en interrupteurs |
| Police personnalisée | `QFontDatabase.addApplicationFont()` avec un TTF embarqué — **à condition** qu'elle soit sous SIL OFL ou Apache-2.0 |
| Chiffres à largeur fixe | choisir une famille qui a de vrais chiffres tabulaires, ou une chasse fixe |

## Indisponible — à remplacer, jamais à demander

| Ce qui est impossible | Pourquoi | Ce qu'on met à la place |
| --- | --- | --- |
| **Flou de l'arrière-plan** (verre dépoli sur le jeu) | Qt n'a pas de `backdrop-filter`, et l'overlay est une fenêtre translucide : ce qui est derrière appartient au jeu | un fond translucide uni ou dégradé, éventuellement plus opaque |
| **`box-shadow` / `text-shadow` en QSS** | non implémentés, silencieusement ignorés | une ombre peinte (overlay, figures) ou un `QGraphicsDropShadowEffect` sur un widget de la fenêtre de bureau uniquement |
| **`text-transform`** | Qt le parse et l'ignore — **vérifié** : le texte reste tel quel | mettre en capitales en Python (`.upper()`) |
| **`transition` / `animation` / `transform`** | absents de QSS | une animation Qt (`QVariantAnimation`) si elle est vraiment nécessaire, mais pas sur l'overlay |
| **`opacity` sur un widget** | pas de propriété d'opacité en QSS | des couleurs en `rgba()`, ou `setWindowOpacity` pour la fenêtre entière |
| **`::before` / `::after` avec du contenu** | pas de pseudo-éléments génératifs | un widget de plus, ou du dessin |
| **Flou par image** | trop coûteux à 10 images/seconde | un halo *cuit une seule fois* dans un pixmap au démarrage et réutilisé — acceptable, à signaler |
| **Photo, rendu 3D, dégradé de maillage, imagerie générée** | rien n'est livré comme fichier image, et l'exécutable pèse déjà 99 Mo | de la géométrie |

## Contraintes propres à l'overlay

C'est là que les maquettes se cassent le plus souvent.

- **Il se redessine ~10 fois par seconde par-dessus un jeu**, budget total du
  programme sous 3 % de CPU et 200 Mo. Donc : pas de flou, pas de recomposition de
  grands pixmaps par image, et tout ce qui est coûteux est mis en cache (les icônes
  le sont déjà).
- **Sur une fenêtre translucide, l'anticrénelage sous-pixel du texte est
  désactivé.** Le texte fin y paraît systématiquement plus faible que dans une
  maquette : à petite taille, sur l'overlay, il faut des graisses moyennes plutôt
  que des maigres, et l'ombre peinte n'est pas un luxe.
- **Il est mis à l'échelle par l'utilisateur, de 0,6 à 2,0.** Une direction qui ne
  tient que grâce à un filet d'un pixel disparaît à 0,6 et devient un trait de deux
  pixels à 2,0. Tout doit être exprimé proportionnellement.
- **Il doit rester lisible sur n'importe quel fond**, du noir d'une grotte au blanc
  d'un écran de victoire. C'est la raison d'être du prompt « épreuve du fond
  clair ».
- **Il ne prend jamais le focus et laisse passer les clics.** Aucune conséquence
  visuelle, mais cela veut dire qu'il n'y a **pas de survol** : un design qui repose
  sur un état de hover pour être compréhensible ne peut pas exister ici.
- **Windows interdit tout overlay par-dessus un jeu en plein écran exclusif.**
  Aucune direction artistique ne corrige ça ; c'est pourquoi le guide consacre une
  étape entière au mode fenêtré sans bordure.

## Contraintes propres à la fenêtre de bureau

- **Une `QCheckBox` ne renvoie pas son texte à la ligne.** Un interrupteur étiqueté
  d'une phrase entière fixe un plancher sous la largeur de la fenêtre — c'est un bug
  qui a réellement bloqué la fenêtre à ~950 px. Les libellés sont courts, les
  explications vivent dans une ligne grise en dessous.
- **La mise en page vient des layouts Qt**, pas du style : pas de flex, pas de
  grille CSS, pas de `position: absolute`. Une maquette doit donc être décomposable
  en colonnes et en lignes empilées.
- **Le style est appliqué à la fenêtre, pas à l'application** : l'overlay se peint
  lui-même et les cadres de zone sont volontairement nus.
- Les polices sont nommées en cascade (`"Barlow", "Segoe UI", sans-serif`) et Qt 6
  prend la **première réellement installée** — d'où l'intérêt de nommer une police
  libre en premier, puis un repli Windows.

## La question du site

`site/index.html` est la page de téléchargement et il est censé être le même produit
que l'application : la palette de `src/theme.py` en est reprise mot pour mot. Une
nouvelle direction s'applique donc aussi là-bas — et cette page-là, elle, est du
vrai CSS, sans aucune des limites ci-dessus. Si une direction demande un effet
impossible en Qt, il reste possible sur le site : à décider explicitement plutôt
qu'à laisser diverger.
