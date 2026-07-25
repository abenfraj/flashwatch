\# LoL Enemy Summoner Timer - Claude Code Instructions



\## PROJECT GOAL



Create a Windows desktop application for League of Legends that:



\* NEVER injects into League of Legends.

\* NEVER reads League's memory.

\* NEVER performs inputs or automates gameplay.

\* ONLY reads information visible on the user's screen.



The application must:



\* detect when League of Legends is running

\* automatically locate the in-game chat

\* take screenshots of the chat every 200ms

\* use OCR to read the chat messages

\* detect enemy summoner spell usage

\* start the appropriate cooldown timer

\* display a transparent click-through overlay

\* display champion and summoner spell icons

\* automatically reset when a new game starts



The project MUST work without pressing any keys.



\---



\## TECHNOLOGIES



Use:



\* Python 3.13

\* PySide6 (GUI)

\* mss (screenshots)

\* RapidOCR

\* OpenCV

\* Pillow

\* psutil

\* requests

\* numpy

\* pywin32

\* keyboard

\* asyncio



install:



````bash

pip install:



```bash

pip install PySide6 mss rapidocr-onnxruntime opencv-python pillow psutil requests numpy pywin32 keyboard

````



\---



\## FILE STRUCTURE



```text

LOLTimer/



assets/

&#x20;   cache/

&#x20;       champions/

&#x20;       spells/



src/



main.py



overlay.py

ocr.py

timer\_manager.py

game\_detector.py

chat\_detector.py

riot\_assets.py

message\_parser.py

cooldowns.py

ui.py

settings.py



requirements.txt

```



\---



\## OVERLAY



The overlay must be:



\* transparent

\* always on top

\* click through

\* draggable

\* resizable

\* movable anywhere on screen



Display example:



```text

\--------------------------------



ENEMY SUMMONERS





TOP



Darius



\[ICON]



Flash



4:23





MID



Ahri



\[ICON]



Flash



2:31





ADC



Jinx



READY





\--------------------------------

```



\---



\## CHAT DETECTION



DO NOT HARDCODE THE CHAT POSITION.



The application must automatically detect:



\* 1080p

\* 1440p

\* 4k

\* windowed mode

\* fullscreen mode

\* different HUD scales



Use OpenCV template matching to find:



\* chat background

\* timestamps

\* brackets



crop only the chat area.



\---



\## OCR



Take screenshots every:



```text

200ms

```



perform:



```text

screenshot

↓



crop chat



↓



OCR



↓



clean text



↓



parse messages



↓



update timers



↓



update overlay

```



OCR must ignore:



```text

player chat



pings



emotes



all messages that are not:



Champion used Flash

Champion used Ghost

Champion used Teleport

Champion used Heal

Champion used Ignite

Champion used Barrier

Champion used Cleanse

Champion used Exhaust

Champion used Smite

```



\---



\## DUPLICATE DETECTION



The same message will appear several times.



Never trigger twice.



store:



```python

messages = {



"Ahri Flash 13:23",

"Lux Heal 21:14"



}

```



If it already exists:



```text

ignore

```



\---



\## COOLDOWNS



```text

Flash



300





Ghost



240





Heal



240





Teleport



360





Ignite



180





Barrier



180





Cleanse



210





Exhaust



240





Smite



90

```



store everything in:



```python

cooldowns.py

```



\---



\## RIOT ASSETS



On startup:



```text

download:



latest version



↓



champion.json



↓



summoner.json



↓



cache icons

```



examples:



```text

Champion



Ahri.png



Darius.png



Viego.png



etc...







Spells



SummonerFlash.png



SummonerTeleport.png



SummonerHeal.png



etc...

```



cache them locally.



\---



\## ICON SUPPORT



display:



```text

champion icon



\+



spell icon



\+



remaining time

```



example:



```text

Ahri





\[ICON]



Flash





\[SPELL ICON]





4:23

```



\---



\## GAME DETECTION



Automatically detect:



```text

LeagueClient.exe



or



League of Legends.exe

```



If the game closes:



```text

clear timers

```



If another game starts:



```text

clear timers

```



everything must reset automatically.



\---



\## PERFORMANCE



maximum CPU usage:



```text

under 3%

```



maximum RAM:



```text

under 200MB

```



Use:



```text

threads



\+



asyncio



\+



OCR only on the cropped region.

```



\---



\## SAFETY REQUIREMENTS



DO NOT:



\* inject DLLs

\* hook League

\* read memory

\* automate gameplay

\* perform mouse inputs

\* perform keyboard inputs

\* communicate with Riot's servers except Data Dragon assets



ONLY:



```text

screen capture



↓



OCR



↓



timers



↓



overlay

```



\---



\## OPTIONAL FEATURES



Add support for:



```text

audio notifications



↓



Flash READY



↓



Teleport READY



↓



5 seconds remaining warning



↓



sorting by role



↓



different overlay themes



↓



saving overlay position

```



\---



\## EXPECTED WORKFLOW



```text

League starts



↓



detect game



↓



detect chat



↓



OCR every 200ms



↓



detect:



Ahri used Flash



↓



start:



300 seconds



↓



display:



Ahri



Flash



4:59



↓



countdown



↓



00:00



↓



READY



↓



optional audio notification



↓



continue monitoring

```



\---



\## IMPORTANT



This project must NEVER:



\* interact with League's memory

\* inject into League

\* modify League files

\* automate gameplay



It must behave like a screen-reader application that only observes pixels displayed on the user's monitor and computes timers from publicly visible information.



The objective is for the entire application to work automatically after launching it, requiring no user interaction during the game.



